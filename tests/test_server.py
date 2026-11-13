"""Web app API: uploads, analyses, remediation, jobs, review, pipelines and auth."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient

from anomalyguard.monitor.api import create_app
from anomalyguard.monitor.settings import ServerSettings

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture()
def pipeline_dir(tmp_path) -> Path:
    d = tmp_path / "pipelines"
    d.mkdir()
    return d


@pytest.fixture()
def client(tmp_path, pipeline_dir, monkeypatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    settings = ServerSettings(pipeline_dirs=[pipeline_dir], max_upload_mb=5)
    with TestClient(create_app(tmp_path / "state" / "ag.db", settings)) as c:
        yield c


def upload(client: TestClient, path: Path | str, name: str | None = None) -> dict:
    data = Path(path).read_bytes()
    r = client.post("/api/datasets", files={"file": (name or Path(path).name, data, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def analyze(client: TestClient, dataset_id: str, **options) -> dict:
    body = {"dataset_id": dataset_id, "detectors": ["mad", "iforest"], **options}
    r = client.post("/api/analyses?wait=true", json=body)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["job"]["status"] == "success", out["job"]
    return client.get(f"/api/analyses/{out['analysis']['id']}").json()


def test_index_and_static(client):
    page = client.get("/")
    assert page.status_code == 200 and "<title>AnomalyGuard</title>" in page.text
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert page.headers["x-content-type-options"] == "nosniff"


def test_upload_profile_and_limits(client, orders_csv, tmp_path):
    meta = upload(client, orders_csv)
    assert meta["rows"] > 0 and "unit_price" in meta["columns"]
    assert client.get("/api/datasets").json()[0]["id"] == meta["id"]

    prof = client.get(f"/api/datasets/{meta['id']}/profile").json()
    assert 0 < prof["quality"]["score"] <= 1
    cols = {c["name"]: c for c in prof["columns"]}
    assert cols["unit_price"]["histogram"]["counts"]
    assert "region" in prof["suggestions"]["group_by"]
    rows = client.get(f"/api/datasets/{meta['id']}/rows?limit=5").json()
    assert len(rows["rows"]) == 5 and rows["total"] == meta["rows"]

    # unsupported type, path tricks, empty files and oversized uploads are rejected
    bad = client.post("/api/datasets", files={"file": ("evil.exe", b"MZ", "application/x")})
    assert bad.status_code == 422
    sneaky = client.post(
        "/api/datasets", files={"file": ("../../etc/x.csv", b"a,b\n1,2\n", "text/csv")}
    )
    assert sneaky.status_code == 201
    stored = list((tmp_path / "state" / "uploads").rglob("x.csv"))
    assert len(stored) == 1 and ".." not in str(stored[0].relative_to(tmp_path))
    assert (
        client.post("/api/datasets", files={"file": ("e.csv", b"", "text/csv")}).status_code == 422
    )
    big = b"a,b\n" + b"1,2\n" * (2 * 1024 * 1024)  # ~8 MB > 5 MB limit
    assert (
        client.post("/api/datasets", files={"file": ("big.csv", big, "text/csv")}).status_code
        == 413
    )
    assert client.get("/api/datasets/nothere/profile").status_code == 404
    assert client.get("/api/datasets/../../x/profile").status_code == 404
    assert client.delete(f"/api/datasets/{meta['id']}").json()["deleted"] == meta["id"]
    assert client.get(f"/api/datasets/{meta['id']}").status_code == 404


def test_analyze_remediate_download(client):
    meta = upload(client, EXAMPLES / "data" / "orders.csv")
    bad = client.post(
        "/api/analyses?wait=true", json={"dataset_id": meta["id"], "group_by": "nope"}
    )
    assert bad.status_code == 422
    analysis = analyze(client, meta["id"], group_by="region", sensitivity="medium")
    aid = analysis["id"]
    assert analysis["status"] == "success" and analysis["summary"]["n_anomalies"] > 0
    assert analysis["breakdown"]["by_column"]["unit_price"] > 0

    # recorded as a run, with stored findings
    run = client.get(f"/api/runs/{analysis['run_id']}").json()
    assert run["kind"] == "analysis" and run["pipeline"] == "analysis:orders.csv"
    assert "anomalies.json" in run["artifacts"]

    rows = client.get(f"/api/analyses/{aid}/rows?limit=10").json()
    assert rows["total"] > 0 and len(rows["rows"]) == 10
    first = rows["rows"][0]
    assert first["cells"] or first["row_findings"]
    for cell in first["cells"].values():
        assert {"detector", "reason", "severity", "score"} <= set(cell[0])
    by_col = client.get(f"/api/analyses/{aid}/rows?column=unit_price&limit=500").json()
    assert all("unit_price" in r["cells"] for r in by_col["rows"])
    high = client.get(f"/api/analyses/{aid}/rows?severity=high&limit=500").json()
    assert high["total"] <= rows["total"]
    everything = client.get(f"/api/analyses/{aid}/rows?only_anomalous=false&limit=20").json()
    assert everything["total"] == meta["rows"]

    # remediation preview: per-column strategies, diff, artifacts
    policy = {
        "default": {"missing": "auto", "outlier": "cap"},
        "columns": {"unit_price": {"outlier": "flag"}},
    }
    rem = client.post(f"/api/analyses/{aid}/remediate", json=policy).json()
    assert rem["summary"]["cells_changed"] > 0 and rem["n_flagged"] > 0
    ch = client.get(f"/api/analyses/{aid}/changes?limit=5").json()
    assert ch["total"] == rem["n_changes"] and {"before", "after", "strategy"} <= set(
        ch["items"][0]
    )
    assert all(
        c["column"] == "quantity"
        for c in client.get(f"/api/analyses/{aid}/changes?column=quantity").json()["items"]
    )
    bad_policy = client.post(f"/api/analyses/{aid}/remediate", json={"default": {"outlier": "x"}})
    assert bad_policy.status_code == 422

    csv = client.get(f"/api/analyses/{aid}/download/cleaned.csv")
    assert csv.status_code == 200 and csv.text.startswith("order_id,")
    assert "orders_cleaned.csv" in csv.headers["content-disposition"]
    md = client.get(f"/api/analyses/{aid}/download/remediation.md")
    assert md.text.startswith("# Remediation report")
    assert client.get(f"/api/analyses/{aid}/download/remediation.json").json()["summary"]
    assert client.get(f"/api/analyses/{aid}/download/../../meta.json").status_code == 404
    assert client.get(f"/api/analyses/{aid}/download/meta.json").status_code == 404
    assert client.get(f"/api/runs/{analysis['run_id']}/artifacts/cleaned.csv").status_code == 200
    run = client.get(f"/api/runs/{analysis['run_id']}").json()
    assert run["cells_changed"] == rem["summary"]["cells_changed"]

    # run anomalies: paginated, filtered, sorted
    r = client.get(f"/api/runs/{analysis['run_id']}/anomalies?limit=5&offset=5&sort=score")
    total = int(r.headers["x-total-count"])
    assert total == analysis["summary"]["n_findings"] and len(r.json()) == 5
    scores = [a["score"] for a in r.json()]
    assert scores == sorted(scores, reverse=True)
    det = client.get(
        f"/api/runs/{analysis['run_id']}/anomalies?detector=grouped(mad by region)"
    ).json()
    assert det and all(a["detector"] == "grouped(mad by region)" for a in det)

    # flagged values -> review queue (deduplicated on repeat)
    queued = client.post(f"/api/analyses/{aid}/review").json()
    assert queued["queued"] > 0
    again = client.post(f"/api/analyses/{aid}/review").json()
    assert again["ids"] == queued["ids"]


def test_jobs_api(client):
    meta = upload(client, EXAMPLES / "data" / "orders.csv")
    r = client.post("/api/analyses", json={"dataset_id": meta["id"], "detectors": ["mad"]})
    assert r.status_code == 202
    job = r.json()["job"]
    assert job["status"] in ("queued", "running", "success")
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in ("success", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "success" and job["result"]["n_anomalies"] > 0
    assert job["progress"] == 1.0
    assert client.get("/api/jobs").json()[0]["id"] == job["id"]
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/summary").json()["analyses"] == 1


def test_review_pagination_filters_and_bulk(client):
    meta = upload(client, EXAMPLES / "data" / "orders.csv")
    analysis = analyze(client, meta["id"], group_by="region")
    aid = analysis["id"]
    client.post(
        f"/api/analyses/{aid}/remediate",
        json={"default": {"outlier": "flag", "missing": "flag"}},
    )
    n = client.post(f"/api/analyses/{aid}/review").json()["queued"]
    assert n > 20

    page = client.get("/api/review?limit=10&offset=10")
    assert int(page.headers["x-total-count"]) == n and len(page.json()) == 10
    facets = client.get("/api/review/facets").json()
    assert facets["counts"]["pending"] == n
    cols = {f["value"] for f in facets["columns"]}
    dets = {f["value"] for f in facets["detectors"]}
    assert "unit_price" in cols and "missing" in dets
    price = client.get("/api/review?column=unit_price&limit=1000").json()
    assert price and all(i["column"] == "unit_price" for i in price)

    detail = client.get(f"/api/review/{price[0]['id']}").json()
    assert detail["row"]["unit_price"] is not None and detail["run"]["id"] == analysis["run_id"]
    assert client.get("/api/review/999999").status_code == 404

    # single item: approve with an edited final value
    item = price[0]
    approved = client.post(f"/api/review/{item['id']}/approve", json={"value": 99.5}).json()
    assert approved["status"] == "approved" and approved["resolved_value"] == 99.5

    # bulk: explicit ids, then everything matching a filter
    ids = [i["id"] for i in price[1:4]]
    out = client.post("/api/review/bulk", json={"action": "reject", "ids": ids}).json()
    assert out["updated"] == 3
    again = client.post("/api/review/bulk", json={"action": "reject", "ids": ids}).json()
    assert again["skipped"] == 3

    missing_before = client.get("/api/review?detector=missing").headers["x-total-count"]
    out = client.post(
        "/api/review/bulk",
        json={"action": "approve", "all_matching": True, "filter": {"detector": "missing"}},
    ).json()
    assert out["updated"] == int(missing_before) > 0
    assert client.get("/api/review?detector=missing").headers["x-total-count"] == "0"

    # apply: approved values are written into the analysis's cleaned file
    applied = client.post("/api/review/bulk", json={"action": "apply", "ids": [item["id"]]}).json()
    assert applied["applied"] == 1
    assert client.get(f"/api/review/{item['id']}").json()["item"]["status"] == "applied"
    cleaned = client.get(f"/api/analyses/{aid}/download/cleaned.csv").text
    assert "99.5" in cleaned

    # false positive feeds the feedback loop
    fp_items = client.get("/api/review?column=unit_price&limit=3").json()
    out = client.post(
        "/api/review/bulk", json={"action": "false_positive", "ids": [i["id"] for i in fp_items]}
    ).json()
    assert out["updated"] == len(fp_items)
    precision = client.get("/api/feedback").json()["precision"]
    assert any(v["false_positive"] >= 1 for v in precision.values())
    single = client.get("/api/review?column=quantity&limit=1").json()
    if single:
        r = client.post(f"/api/review/{single[0]['id']}/false-positive").json()
        assert r["item"]["status"] == "rejected"

    assert client.post("/api/review/bulk", json={"action": "nuke", "ids": [1]}).status_code == 422
    assert client.post("/api/review/bulk", json={"action": "approve", "ids": []}).status_code == 422


def test_pipelines_list_create_validate_run(client, pipeline_dir):
    assert client.get("/api/pipelines").json()["pipelines"] == []
    templates = client.get("/api/pipelines/templates").json()
    assert {t["name"] for t in templates} >= {"csv_quality", "timeseries_monitor"}

    meta = upload(client, EXAMPLES / "data" / "orders.csv")
    r = client.post(
        "/api/pipelines",
        json={
            "name": "orders_ui",
            "template": "csv_quality",
            "source": f"dataset:{meta['id']}",
            "group_by": "region",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["valid"] and (pipeline_dir / "orders_ui.yaml").exists()
    assert "group_by: region" in created["yaml"]
    assert client.post("/api/pipelines", json={"name": "orders_ui"}).status_code == 409
    assert client.post("/api/pipelines", json={"name": "../evil"}).status_code == 422
    assert client.post("/api/pipelines", json={"name": "x", "template": "nope"}).status_code == 422

    listed = client.get("/api/pipelines").json()["pipelines"]
    assert [p["name"] for p in listed] == ["orders_ui"]
    pid = listed[0]["id"]
    assert client.get(f"/api/pipelines/{pid}").json()["yaml"].startswith("#")
    assert client.post(f"/api/pipelines/{pid}/validate").json()["valid"]
    assert client.post("/api/pipelines/validate", json={"yaml": "name: x"}).json()["valid"] is False
    assert client.get("/api/pipelines/nope").status_code == 404

    job = client.post(f"/api/pipelines/{pid}/run?wait=true").json()["job"]
    assert job["status"] == "success", job
    run_id = job["result"]["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["pipeline"] == "orders_ui" and run["kind"] == "pipeline"
    assert any(a.startswith("data") for a in run["artifacts"])
    assert client.get(f"/api/pipelines/{pid}").json()["recent_runs"][0]["id"] == run_id
    assert client.get("/api/runs?kind=pipeline").headers["x-total-count"] == "1"
    series = client.get("/api/metrics/series").json()["series"]
    assert series[0]["pipeline"] == "orders_ui" and series[0]["points"][0]["anomaly_rate"] > 0

    # edit + save YAML; invalid YAML is refused
    text = created["yaml"].replace("every: 1h", "every: 2h")
    assert (
        client.put(f"/api/pipelines/{pid}", json={"yaml": text}).json()["interval_seconds"] == 7200
    )
    assert client.put(f"/api/pipelines/{pid}", json={"yaml": "name: [x"}).status_code == 422

    # a failing pipeline makes a failed job
    (pipeline_dir / "broken.yaml").write_text(
        "name: broken\nsource: {type: csv, path: missing.csv}\n", encoding="utf-8"
    )
    broken = next(
        p for p in client.get("/api/pipelines").json()["pipelines"] if p["name"] == "broken"
    )
    job = client.post(f"/api/pipelines/{broken['id']}/run?wait=true").json()["job"]
    assert job["status"] == "failed" and "missing.csv" in job["error"]


def test_settings_thresholds_detectors(client):
    s = client.get("/api/settings").json()
    assert s["server"]["auth_enabled"] is False and s["state"]["writable"]
    assert any(e["name"] == "ANOMALYGUARD_API_KEY" for e in s["env"])
    assert {d["name"] for d in client.get("/api/detectors").json()} >= {"mad", "iforest", "lof"}
    assert client.put("/api/thresholds/mad", json={"multiplier": 1.3}).json()["multiplier"] == 1.3
    assert client.get("/api/thresholds").json()[0]["multiplier"] == 1.3
    assert client.put("/api/thresholds/mad", json={"multiplier": 99}).status_code == 422
    assert client.delete("/api/thresholds/mad").json()["removed"] is True


def test_api_key_and_cors(tmp_path):
    settings = ServerSettings(
        api_key="s3cret", cors_origins=["http://example.test"], pipeline_dirs=[tmp_path]
    )
    client = TestClient(create_app(tmp_path / "ag.db", settings))
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200  # the page itself loads and asks for the key
    assert client.get("/api/auth").json() == {"auth_enabled": True, "authenticated": False}
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/summary", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/summary", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/summary", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/auth", headers={"X-API-Key": "s3cret"}).json()["authenticated"]

    pre = client.options(
        "/api/summary",
        headers={
            "Origin": "http://example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    assert pre.headers["access-control-allow-origin"] == "http://example.test"
    other = client.get("/health", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in other.headers


def test_settings_from_env():
    s = ServerSettings.from_env(
        {
            "ANOMALYGUARD_API_KEY": " s3cr3t-key ",
            "ANOMALYGUARD_CORS_ORIGINS": "http://a.test, http://b.test",
            "ANOMALYGUARD_MAX_UPLOAD_MB": "12.5",
            "ANOMALYGUARD_PIPELINE_DIRS": "one,two",
            "ANOMALYGUARD_WORKERS": "nope",
        }
    )
    assert s.api_key == "s3cr3t-key" and s.cors_origins == ["http://a.test", "http://b.test"]
    assert s.max_upload_bytes == int(12.5 * 1024 * 1024)
    assert [p.name for p in s.pipeline_dirs] == ["one", "two"] and s.workers == 2
    assert "s3cr3t" not in str(s.describe())
    assert ServerSettings.from_env({}).auth_enabled is False


def test_sample_datasets(client):
    r = client.post("/api/datasets/sample", json={"kind": "orders"})
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["name"] == "sample_orders.csv" and meta["rows"] == 1000
    assert client.get(f"/api/datasets/{meta['id']}/profile").status_code == 200

    sensor = client.post("/api/datasets/sample", json={"kind": "sensor"}).json()
    assert sensor["rows"] > 0 and sensor["id"] != meta["id"]
    names = {d["name"] for d in client.get("/api/datasets").json()}
    assert {"sample_orders.csv", "sample_sensor.csv"} <= names

    bad = client.post("/api/datasets/sample", json={"kind": "nope"})
    assert bad.status_code == 422


def test_incidents_for_an_analysis(client):
    meta = client.post("/api/datasets/sample", json={"kind": "orders"}).json()
    analysis = analyze(client, meta["id"], group_by="region")
    run_id = analysis["run_id"]

    out = client.get(f"/api/runs/{run_id}/incidents").json()
    assert out["run_id"] == run_id and out["muted"] == 0
    items = out["incidents"]
    assert items and out["open"] == len(items)
    ranks = [{"high": 0, "medium": 1, "low": 2}[i["severity"]] for i in items]
    assert ranks == sorted(ranks)
    price = next(i for i in items if i["column"] == "unit_price" and i["kind"] == "outlier")
    assert price["entity"] == "sample_orders.unit_price"
    assert price["title"].startswith("Values") and price["explanation"]
    assert {"grouped(mad by region)", "grouped(iforest by region)"} <= set(price["detectors"])
    exp = price["expected"]
    assert exp["low"] <= exp["center"] <= exp["high"]
    assert price["actual"]["value"] > exp["high"] and price["delta_pct"] > 0
    assert price["status"] == "open" and price["chart"] == "distribution"
    kinds = {i["kind"] for i in items}
    assert {"missing", "duplicates"} <= kinds  # from the profile's quality metrics
    # First run of this source: no baseline, so missing values are not called a spike.
    missing = [i for i in items if i["kind"] == "missing"]
    assert all(i["title"] == "Missing values" and i["direction"] is None for i in missing)
    assert all("no baseline" in i["explanation"] for i in missing)

    chart = client.get(f"/api/runs/{run_id}/incidents/{price['id']}/chart").json()
    assert chart["type"] == "distribution" and len(chart["counts"]) == len(chart["edges"]) - 1
    assert chart["band"]["low"] == exp["low"] and chart["marks"]
    assert any(m["v"] > chart["band"]["high"] for m in chart["marks"])
    dup = next(i for i in items if i["kind"] == "duplicates")
    hist = client.get(f"/api/runs/{run_id}/incidents/{dup['id']}/chart").json()
    assert hist["type"] == "history" and hist["points"][-1]["v"] == dup["actual"]["value"]
    assert client.get(f"/api/runs/{run_id}/incidents/nope/chart").status_code == 404
    assert client.get("/api/runs/99999/incidents").status_code == 404

    # mark as normal: every finding becomes false-positive feedback
    qty = next(i for i in items if i["column"] == "quantity" and i["kind"] == "outlier")
    r = client.post(f"/api/runs/{run_id}/incidents/{qty['id']}/triage", json={"action": "normal"})
    assert r.status_code == 200, r.text
    assert r.json()["incident"]["status"] == "normal" and r.json()["feedback"] == qty["n_findings"]
    precision = client.get("/api/feedback").json()["precision"]
    assert sum(v["false_positive"] for v in precision.values()) == qty["n_findings"]

    # confirm: true positives, and the flagged cells go to the review queue
    r = client.post(
        f"/api/runs/{run_id}/incidents/{price['id']}/triage", json={"action": "confirm"}
    )
    body = r.json()
    assert body["incident"]["status"] == "confirmed" and body["queued"] == price["n_rows"]
    queued = client.get(f"/api/review?run_id={run_id}&column=unit_price&limit=1000").json()
    assert len(queued) == price["n_rows"]
    assert any(q["suggestion"] == round(exp["high"], 4) for q in queued)  # capped to the band
    again = client.post(
        f"/api/runs/{run_id}/incidents/{price['id']}/triage", json={"action": "confirm"}
    ).json()
    assert again["queued"] == price["n_rows"]  # no duplicates in the queue
    assert int(client.get("/api/review?status=all").headers["x-total-count"]) == price["n_rows"]
    reopened = client.post(
        f"/api/runs/{run_id}/incidents/{price['id']}/triage", json={"action": "reopen"}
    ).json()
    assert reopened["incident"]["status"] == "open"
    bad = client.post(f"/api/runs/{run_id}/incidents/{price['id']}/triage", json={"action": "x"})
    assert bad.status_code == 422

    # mute for 24 h: hidden by default, listed with include_muted, and unmutable
    m = client.post(f"/api/runs/{run_id}/incidents/{dup['id']}/mute", json={"hours": 24}).json()
    assert m["kind"] == "duplicates" and m["until"] > m["created_at"]
    out = client.get(f"/api/runs/{run_id}/incidents").json()
    assert out["muted"] == 1 and all(i["id"] != dup["id"] for i in out["incidents"])
    every = client.get(f"/api/runs/{run_id}/incidents?include_muted=true").json()["incidents"]
    assert next(i for i in every if i["id"] == dup["id"])["muted_until"] == m["until"]
    assert [x["id"] for x in client.get("/api/incidents/mutes").json()] == [m["id"]]
    bad_mute = client.post(f"/api/runs/{run_id}/incidents/{dup['id']}/mute", json={"hours": 0})
    assert bad_mute.status_code == 422
    # mutes follow the source, so the next analysis of the same file is muted too
    second = analyze(client, meta["id"], group_by="region")
    nxt = client.get(f"/api/runs/{second['run_id']}/incidents").json()
    assert nxt["muted"] == 1
    assert client.delete(f"/api/incidents/mutes/{m['id']}").json()["deleted"] == m["id"]
    assert client.delete(f"/api/incidents/mutes/{m['id']}").status_code == 404
    assert client.get(f"/api/runs/{run_id}/incidents").json()["muted"] == 0

    feed = client.get("/api/incidents?limit=5").json()
    assert len(feed) == 5 and feed[0]["run_id"] == second["run_id"]


def test_incidents_time_series_band(client):
    meta = client.post("/api/datasets/sample", json={"kind": "sensor"}).json()
    analysis = analyze(client, meta["id"], detectors=["seasonal", "cusum"], time_column="timestamp")
    items = client.get(f"/api/runs/{analysis['run_id']}/incidents").json()["incidents"]
    kinds = {i["kind"] for i in items if i["column"] == "temperature"}
    assert {"pattern", "level_shift"} <= kinds
    shift = next(i for i in items if i["kind"] == "level_shift")
    assert shift["title"] == "Level shift detected" and shift["chart"] == "series"
    chart = client.get(f"/api/runs/{analysis['run_id']}/incidents/{shift['id']}/chart").json()
    n = len(chart["x"])
    assert chart["type"] == "series" and chart["time"] == "timestamp" and chart["period"] == 24
    assert n == len(chart["y"]) == len(chart["low"]) == len(chart["high"]) and n <= 1500
    assert all(
        lo <= hi for lo, hi in zip(chart["low"], chart["high"], strict=True) if lo is not None
    )
    outside = [
        i for i in chart["flagged"] if not chart["low"][i] <= chart["y"][i] <= chart["high"][i]
    ]
    assert outside  # the flagged readings break out of the expected band


def test_health_overview(client):
    empty = client.get("/api/health/overview").json()
    assert empty["sources"] == [] and empty["kpis"]["monitored"] == 0
    meta = client.post("/api/datasets/sample", json={"kind": "orders"}).json()
    analyze(client, meta["id"])
    analyze(client, meta["id"])
    h = client.get("/api/health/overview").json()
    assert h["kpis"]["monitored"] == 1 and h["kpis"]["rows_scanned"] == 2000
    src = h["sources"][0]
    assert src["name"] == "sample_orders" and src["kind"] == "analysis"
    assert src["status"] in ("degraded", "warning") and src["open_incidents"] > 0
    assert len(src["quality_series"]) == 2 and src["trend"] == 0
    assert h["kpis"]["open_incidents"] == src["open_incidents"]
