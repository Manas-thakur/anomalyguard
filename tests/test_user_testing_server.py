"""Regression tests for server, pipeline-config, alert and review issues found in
hands-on testing (invalid pipeline files, silent webhook failures, review and
feedback edge cases, run numbering)."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import httpx
import pandas as pd
import pytest

from anomalyguard.alert.base import AlertMessage, Notifier, Severity
from anomalyguard.alert.manager import AlertManager
from anomalyguard.alert.notifiers import ConsoleNotifier, WebhookNotifier
from anomalyguard.cli import main
from anomalyguard.monitor import doctor
from anomalyguard.monitor.catalog import PipelineCatalog
from anomalyguard.monitor.feedback import FeedbackLoop, resolve_detector
from anomalyguard.monitor.store import MetricsStore
from anomalyguard.pipeline.config import ConfigError, PipelineConfig
from anomalyguard.remediate.review import ReviewQueue

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

BAD_FILES = {
    "syntax.yaml": "name: x\nsource: [unclosed\n  - foo: : bar\n",
    "noname.yaml": "source: {type: csv, path: data.csv}\n",
    "nosource.yaml": "name: nosource\ndetectors: [mad]\n",
    "badschedule.yaml": "name: sched\nsource: {type: csv, path: data.csv}\nschedule: {every: banana}\n",
    "baddetector.yaml": "name: det\nsource: {type: csv, path: data.csv}\ndetectors: [nosuch]\n",
}


@pytest.fixture()
def pipeline_dir(tmp_path) -> Path:
    d = tmp_path / "pipelines"
    d.mkdir()
    pd.DataFrame({"x": range(50)}).to_csv(d / "data.csv", index=False)
    (d / "ok.yaml").write_text("name: ok\nsource: {type: csv, path: data.csv}\ndetectors: [mad]\n")
    for name, text in BAD_FILES.items():
        (d / name).write_text(text)
    # not pipelines: a schema file and an unrelated YAML document
    (d / "orders.schema.yaml").write_text("name: orders\nfields:\n  x: {dtype: integer}\n")
    (d / "notes.yaml").write_text("- just\n- a list\n")
    return d


# ----------------------------------------------------------------------
# M6: invalid pipeline files
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "schedule,message",
    [
        ({"every": "banana"}, "schedule.every: invalid duration 'banana'"),
        ({"every": "0s"}, "schedule.every: duration must be positive"),
        ({"interval_seconds": "soon"}, "schedule.interval_seconds: invalid duration"),
        ("5m", "schedule must be a mapping"),
    ],
)
def test_bad_schedule_is_a_config_error_at_load(schedule, message):
    with pytest.raises(ConfigError, match=message):
        PipelineConfig.from_dict({"name": "x", "source": {"path": "a.csv"}, "schedule": schedule})
    ok = PipelineConfig.from_dict(
        {"name": "x", "source": {"path": "a.csv"}, "schedule": {"every": "2h"}}
    )
    assert ok.interval_seconds == 7200


def test_load_error_names_the_file(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(BAD_FILES["badschedule.yaml"])
    with pytest.raises(ConfigError) as err:
        PipelineConfig.load(p)
    assert str(p) in str(err.value) and "schedule.every" in str(err.value)
    p.write_text(BAD_FILES["syntax.yaml"])
    with pytest.raises(ConfigError, match=r"Invalid YAML: .*\(line 3, column 8\)"):
        PipelineConfig.load(p)


def test_catalog_lists_invalid_files_and_never_raises(pipeline_dir):
    catalog = PipelineCatalog([pipeline_dir], None, pipeline_dir)
    listed = {p["file"]: p for p in catalog.list()}
    assert set(listed) == {"ok.yaml", *BAD_FILES}  # schema file and plain list left out
    assert listed["ok.yaml"]["valid"]
    for name in BAD_FILES:
        assert not listed[name]["valid"] and listed[name]["error"], name
    assert "schedule.every" in listed["badschedule.yaml"]["error"]
    assert listed["badschedule.yaml"]["name"] == "sched"
    assert listed["syntax.yaml"]["name"] is None


def test_run_reports_bad_schedule_without_schedule_flag(pipeline_dir, monkeypatch, capsys):
    monkeypatch.chdir(pipeline_dir.parent)
    assert main(["run", str(pipeline_dir / "badschedule.yaml")]) == 1
    err = capsys.readouterr().err
    assert "badschedule.yaml" in err and "schedule.every: invalid duration 'banana'" in err


def test_doctor_continues_past_bad_files(pipeline_dir, tmp_path, capsys):
    info = doctor.collect(tmp_path / "state" / "ag.db", [pipeline_dir])
    by_file = {Path(p["file"]).name: p for p in info["pipelines"]}
    assert set(by_file) == {"ok.yaml", *BAD_FILES}
    assert by_file["ok.yaml"]["valid"] and not by_file["badschedule.yaml"]["valid"]
    assert (
        main(["doctor", "--db", str(tmp_path / "s" / "ag.db"), "--pipeline-dir", str(pipeline_dir)])
        == 0
    )
    out = capsys.readouterr().out
    assert "badschedule.yaml" in out and "invalid duration 'banana'" in out
    assert "invalid pipeline :" not in out  # the file name is never lost


def test_missing_source_file_is_a_warning(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    (d / "a.yaml").write_text("name: a\nsource: {type: csv, path: missing.csv}\n")
    info = PipelineCatalog([d], None, d).list()[0]
    assert info["valid"] and "source file not found" in info["warnings"][0]


# ----------------------------------------------------------------------
# M10: failed alert deliveries
# ----------------------------------------------------------------------
def _webhook(status: int) -> WebhookNotifier:
    return WebhookNotifier(
        "https://hooks.example.test/services/SECRET",
        min_severity="info",
        transport=httpx.MockTransport(lambda req: httpx.Response(status)),
    )


def _refusing() -> WebhookNotifier:
    def refuse(req):
        raise httpx.ConnectError("connection refused", request=req)

    return WebhookNotifier("http://127.0.0.1:9/hook", transport=httpx.MockTransport(refuse))


def test_webhook_failure_is_logged_with_status(caplog):
    msg = AlertMessage("rate high", severity=Severity.ERROR, source="shop")
    with caplog.at_level(logging.WARNING, logger="anomalyguard.alert"):
        assert _webhook(500).send(msg) is False
        assert _refusing().send(msg) is False
    text = caplog.text
    assert "HTTP 500" in text and "ConnectError" in text and "rate high" in text
    assert "SECRET" not in text  # webhook tokens are not logged


def test_dispatch_records_per_channel_status():
    msg = AlertMessage("rate high", severity=Severity.ERROR, source="shop")

    class Broken(Notifier):
        kind = "custom"

        def send(self, message):
            raise RuntimeError("boom")

    partial = AlertManager([ConsoleNotifier(), _webhook(503)]).dispatch([msg])[0]
    assert partial.status == "partial" and partial.channels == ["console"]
    assert partial.deliveries[1] == {
        "channel": "webhook",
        "ok": False,
        "error": "HTTP 503 Service Unavailable",
    }
    failed = AlertManager([_webhook(500), Broken()]).dispatch([msg])[0]
    assert failed.status == "failed" and failed.channels == [] and not failed.delivered
    assert failed.deliveries[1]["error"] == "RuntimeError: boom"
    sent = AlertManager([_webhook(200)]).dispatch([msg])[0]
    assert sent.status == "sent" and sent.channels == ["webhook"] and sent.delivered
    d = partial.to_dict()
    assert d["deliveries"] and d["status"] == "partial"


def test_pipeline_records_failed_delivery(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"v": [1.0] * 60 + [1000.0] * 10}).to_csv(tmp_path / "d.csv", index=False)
    cfg = PipelineConfig.from_dict(
        {
            "name": "hook",
            "source": {"path": "d.csv"},
            "detectors": ["mad"],
            "alerts": {
                "rules": [{"metric": "n_anomalies", "op": ">", "value": 0, "severity": "error"}],
                "notifiers": [{"type": "webhook", "url": "http://127.0.0.1:9/hook"}],
                "rate_limit": False,
            },
        },
        base_dir=tmp_path,
    )
    from anomalyguard.pipeline.executor import PipelineExecutor

    with caplog.at_level(logging.WARNING, logger="anomalyguard.alert"):
        result = PipelineExecutor(cfg, console=False).run()
    assert result.ok and result.alerts[0].status == "failed"
    assert result.metrics["alerts_sent"] == 0 and result.metrics["alerts_failed"] == 1
    assert "webhook alert delivery" in caplog.text
    stored = MetricsStore(cfg.db_path).alerts(run_id=result.run_id)[0]
    assert stored["status"] == "failed" and stored["channels"] == ""
    assert stored["deliveries"][0]["channel"] == "webhook" and not stored["deliveries"][0]["ok"]


def test_store_migrates_alerts_table(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER,"
            " created_at TEXT NOT NULL, severity TEXT, title TEXT, status TEXT, channels TEXT)"
        )
        conn.execute("INSERT INTO alerts (created_at, status) VALUES ('2026-01-01', 'sent')")
    store = MetricsStore(db)
    assert store.alerts()[0]["deliveries"] == []
    store.add_alerts(None, [{"title": "t", "status": "partial", "deliveries": [{"channel": "x"}]}])
    assert store.alerts()[0]["deliveries"] == [{"channel": "x"}]


# ----------------------------------------------------------------------
# run numbers
# ----------------------------------------------------------------------
def test_per_pipeline_run_numbers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"v": range(40)}).to_csv(tmp_path / "d.csv", index=False)
    for name in ("a", "b"):
        (tmp_path / f"{name}.yaml").write_text(
            f"name: {name}\nsource: {{path: d.csv}}\ndetectors: [mad]\nalerts: {{enabled: false}}\n"
        )
    assert main(["run", "a.yaml", "b.yaml", "a.yaml"]) == 0
    out = capsys.readouterr().out
    assert "[a] run 1 (#1)" in out and "[b] run 1 (#2)" in out and "[a] run 2 (#3)" in out
    runs = MetricsStore(".anomalyguard/anomalyguard.db").runs()
    assert [(r["pipeline"], r["run_number"]) for r in runs] == [("a", 2), ("b", 1), ("a", 1)]


def test_run_without_monitoring_has_no_none_id(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"v": range(40)}).to_csv(tmp_path / "d.csv", index=False)
    (tmp_path / "p.yaml").write_text(
        "name: nomon\nsource: {path: d.csv}\ndetectors: [mad]\nmonitor: {enabled: false}\n"
        "alerts: {enabled: false}\n"
    )
    assert main(["run", "p.yaml"]) == 0
    assert main(["run", "p.yaml"]) == 0
    out = capsys.readouterr().out
    assert "None" not in out and "[nomon] run 1:" in out and "[nomon] run 2:" in out


# ----------------------------------------------------------------------
# review queue and feedback
# ----------------------------------------------------------------------
def test_reapproving_keeps_reviewer_value(tmp_path):
    q = ReviewQueue(tmp_path / "r.db")
    item = q.add("price", 999.0, "outlier", row_index=3, suggestion=99.9)
    assert q.approve(item, value=120.0)["resolved_value"] == 120.0
    again = q.approve(item, note="bulk")  # no value: keep the reviewer's 120
    assert again["resolved_value"] == 120.0 and again["status"] == "approved"
    q.mark_applied([item])
    assert q.approve(item)["status"] == "applied"  # unchanged value stays applied
    assert q.approve(item, value=130.0)["status"] == "approved"


def test_review_queue_create_false(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReviewQueue(tmp_path / "nope" / "r.db", create=False)
    assert not (tmp_path / "nope").exists()


def test_review_cli_does_not_create_db(tmp_path, capsys):
    db = tmp_path / "typo" / "review.db"
    for argv in (
        ["review", "list", "--db", str(db)],
        ["review", "approve", "1", "--db", str(db)],
        ["feedback", "stats", "--db", str(db)],
        ["findings", "--db", str(db)],
    ):
        assert main(argv) == 1, argv
        assert "database not found" in capsys.readouterr().err
    assert not (tmp_path / "typo").exists()


def test_review_cli_approve_whole_row_item(tmp_path, capsys):
    db = tmp_path / "r.db"
    q = ReviewQueue(db)
    row_item = q.add(None, None, "anomalous row: iforest", row_index=7)
    assert main(["review", "approve", str(row_item), "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "whole row" in out and "no cell value" in out and "None" not in out
    assert main(["review", "list", "--status", "applied", "--db", str(db)]) == 0


def _run_with_findings(tmp_path) -> tuple[MetricsStore, int]:
    store = MetricsStore(tmp_path / "m.db")
    run_id = store.record_run("shop", {"rows": 10}, detectors={"grouped(mad by region)": 1})
    store.add_anomalies(
        run_id,
        [
            {"index": 1969, "column": "price", "detector": "grouped(mad by region)", "score": 4.0},
            {"index": "r-7", "column": None, "detector": "iforest", "score": 2.0},
        ],
    )
    return store, run_id


def test_feedback_row_index_not_double_encoded(tmp_path):
    store, run_id = _run_with_findings(tmp_path)
    ids = [a["id"] for a in store.anomalies(run_id)]
    loop = FeedbackLoop(store)
    for i in ids:
        loop.mark("false_positive", anomaly_id=i)
    recent = {f["anomaly_id"]: f["row_index"] for f in store.feedback()}
    assert recent[ids[0]] == 1969 and recent[ids[1]] == "r-7"


def test_resolve_detector_names(tmp_path):
    store, _ = _run_with_findings(tmp_path)
    assert resolve_detector("tukey") == "iqr"
    assert resolve_detector("MAD") == "mad"
    assert resolve_detector("grouped(mad by region)") == "grouped(mad by region)"
    assert resolve_detector("grouped(iqr by a,b)") == "grouped(iqr by a,b)"
    assert resolve_detector("ensemble[mean](mad,iforest)").startswith("ensemble")
    assert resolve_detector("grouped") == "grouped"
    for bad in ("madd", "grouped(nosuch by x)", ""):
        with pytest.raises(KeyError):
            resolve_detector(bad, store)


def test_feedback_cli_rejects_unknown_detector(tmp_path, capsys):
    store, _ = _run_with_findings(tmp_path)
    db = str(store.path)
    assert main(["feedback", "fp", "--detector", "madd", "--db", db]) == 2
    assert "Unknown detector 'madd'" in capsys.readouterr().err
    assert main(["feedback", "fp", "--detector", "grouped(mad by region)", "--db", db]) == 0
    assert main(["feedback", "fp", "--anomaly-id", "999", "--db", db]) == 1
    err = capsys.readouterr().err
    assert "error: Anomaly 999 not found" in err and "'Anomaly" not in err
    assert "anomalyguard findings" in err


def test_findings_command_lists_ids(tmp_path, capsys):
    store, run_id = _run_with_findings(tmp_path)
    assert main(["findings", str(run_id), "--db", str(store.path)]) == 0
    out = capsys.readouterr().out
    assert "grouped(mad by region)" in out and "1969" in out and "2 stored findings" in out
    assert main(["findings", "--json", "--db", str(store.path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == run_id and len(data["findings"]) == 2
    assert main(["findings", "99", "--db", str(store.path)]) == 1


# ----------------------------------------------------------------------
# HTTP API
# ----------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, pipeline_dir, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from anomalyguard.monitor.api import create_app
    from anomalyguard.monitor.settings import ServerSettings

    monkeypatch.chdir(tmp_path)
    settings = ServerSettings(pipeline_dirs=[pipeline_dir])
    with TestClient(create_app(tmp_path / "state" / "ag.db", settings)) as c:
        yield c


def test_api_pipelines_lists_invalid_files(client):
    r = client.get("/api/pipelines")
    assert r.status_code == 200
    files = {p["file"]: p for p in r.json()["pipelines"]}
    assert not files["badschedule.yaml"]["valid"] and files["ok.yaml"]["valid"]
    pid = files["syntax.yaml"]["id"]
    detail = client.get(f"/api/pipelines/{pid}")
    assert detail.status_code == 200 and "Invalid YAML" in detail.json()["error"]
    assert client.get("/api/settings").status_code == 200


def test_api_run_job_message_and_run_numbers(client):
    pid = {p["file"]: p for p in client.get("/api/pipelines").json()["pipelines"]}["ok.yaml"]["id"]
    for n in (1, 2):
        job = client.post(f"/api/pipelines/{pid}/run?wait=true").json()["job"]
        assert job["status"] == "success"
        assert job["message"].startswith(f"run {n} (#") and "Running" not in job["message"]
    runs = client.get("/api/runs").json()
    assert runs[0]["run_number"] == 2 and runs[0]["kind"] == "pipeline"
    detail = client.get(f"/api/runs/{runs[0]['id']}").json()
    assert detail["run_number"] == 2 and detail["kind"] == "pipeline"


def test_api_alerts_expose_deliveries(client, tmp_path):
    store = MetricsStore(tmp_path / "state" / "ag.db")
    run_id = store.record_run("shop", {"rows": 1})
    deliveries = [
        {"channel": "console", "ok": True, "error": None},
        {"channel": "webhook", "ok": False, "error": "HTTP 500 Internal Server Error"},
    ]
    store.add_alerts(
        run_id,
        [{"title": "t", "status": "partial", "channels": ["console"], "deliveries": deliveries}],
    )
    alert = client.get("/api/alerts").json()[0]
    assert alert["status"] == "partial" and alert["deliveries"] == deliveries
    assert client.get(f"/api/runs/{run_id}").json()["alerts"][0]["deliveries"] == deliveries


def test_api_feedback_raw_row_index_and_detector_check(client, tmp_path):
    store = MetricsStore(tmp_path / "state" / "ag.db")
    run_id = store.record_run("shop", {"rows": 1})
    store.add_anomalies(run_id, [{"index": 1969, "column": "x", "detector": "mad", "score": 3}])
    aid = store.anomalies(run_id)[0]["id"]
    assert client.post("/api/feedback", json={"anomaly_id": aid}).status_code == 200
    assert client.get("/api/feedback").json()["recent"][0]["row_index"] == 1969
    r = client.post("/api/feedback", json={"detector": "nosuch"})
    assert r.status_code == 404 and "Unknown detector" in r.json()["detail"]
    r = client.post("/api/feedback", json={"anomaly_id": 12345})
    assert r.json()["detail"] == "Anomaly 12345 not found"
    assert client.put("/api/thresholds/nosuch", json={"multiplier": 1.5}).status_code == 404
    ok = client.put("/api/thresholds/tukey", json={"multiplier": 1.5})
    assert ok.status_code == 200 and ok.json()["detector"] == "iqr"
    assert (
        client.put("/api/thresholds/grouped(mad by region)", json={"multiplier": 2}).status_code
        == 200
    )


def test_api_markdown_artifact_media_type(client, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Remediation report\n")
    store = MetricsStore(tmp_path / "state" / "ag.db")
    run_id = store.record_run("shop", {"rows": 1, "outputs": {"report": str(report)}})
    r = client.get(f"/api/runs/{run_id}/artifacts/report.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")


def test_api_mute_hours_message(client, tmp_path, pipeline_dir):
    shutil.copy(EXAMPLES / "data" / "orders.csv", pipeline_dir / "orders.csv")
    (pipeline_dir / "orders.yaml").write_text(
        "name: orders\nsource: {path: orders.csv}\ndetectors: [mad]\nalerts: {enabled: false}\n"
    )
    pid = {p["file"]: p for p in client.get("/api/pipelines").json()["pipelines"]}["orders.yaml"][
        "id"
    ]
    run_id = client.post(f"/api/pipelines/{pid}/run?wait=true").json()["job"]["result"]["run_id"]
    incs = client.get(f"/api/runs/{run_id}/incidents").json()["incidents"]
    assert incs
    r = client.post(f"/api/runs/{run_id}/incidents/{incs[0]['id']}/mute", json={"hours": 0})
    assert (
        r.status_code == 422
        and r.json()["detail"] == "hours must be more than 0 and at most 720 (30 days)"
    )


def test_install_hints_point_to_github():
    cmd = doctor.install_command("server")
    assert cmd.startswith('pip install "anomalyguard[server] @ git+https://github.com/')
    assert cmd.endswith('@v0.3.0"')
    assert doctor.install_command(ref="main").endswith('anomalyguard@main"')
    assert all("git+https" in e["install"] for e in doctor.extras_status().values())
