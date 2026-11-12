from __future__ import annotations

import json
import sqlite3
import textwrap

import pandas as pd
import pytest
import yaml

from anomalyguard.monitor import MetricsStore
from anomalyguard.pipeline import (
    TEMPLATES,
    ConfigError,
    PipelineConfig,
    PipelineExecutor,
    Scheduler,
    expand_env,
    parse_duration,
    render_template,
    run_pipeline,
)
from anomalyguard.remediate import ReviewQueue


def write_pipeline(tmp_path, body: str) -> str:
    path = tmp_path / "pipeline.yaml"
    path.write_text(textwrap.dedent(body))
    return str(path)


BASE = """\
name: orders_test
source:
  type: csv
  path: orders.csv
schema:
  path: orders.schema.yaml
detectors:
  - method: mad
    columns: [quantity, unit_price, delivery_days]
  - method: mad
    columns: [unit_price]
    group_by: region
remediation:
  default:
    outlier: cap
alerts:
  rules:
    - {metric: anomaly_rate, op: ">", value: 0.01, severity: warning}
  notifiers:
    - {type: file, path: out/alerts.jsonl}
sink:
  path: out/clean.csv
  anomalies_path: out/anomalies.json
  report_path: out/report.md
monitor:
  db: state/ag.db
state:
  dir: state
"""


def test_end_to_end_run(tmp_path, orders):
    df, labels = orders
    df.to_csv(tmp_path / "orders.csv", index=False)
    cfg = PipelineConfig.load(write_pipeline(tmp_path, BASE))
    result = PipelineExecutor(cfg, console=False).run()
    assert result.status == "success", result.error
    m = result.metrics
    assert m["rows"] == len(df) and m["n_anomalies"] > 0
    assert 0 < m["quality_score"] <= 1
    assert m["rows_dropped"] == int((labels["anomaly_type"] == "duplicate").sum())
    assert m["alerts_sent"] == 1

    clean = pd.read_csv(tmp_path / "out" / "clean.csv")
    assert len(clean) == len(df) - m["rows_dropped"]
    assert clean["quantity"].max() < 50
    report = json.loads((tmp_path / "out" / "anomalies.json").read_text())
    assert report["summary"]["n_anomalies"] == m["n_anomalies"]
    assert "# Remediation report" in (tmp_path / "out" / "report.md").read_text()
    assert (tmp_path / "orders.schema.yaml").exists()  # inferred and saved on first run
    alerts = [json.loads(x) for x in (tmp_path / "out" / "alerts.jsonl").read_text().splitlines()]
    assert alerts[0]["source"] == "orders_test"

    store = MetricsStore(tmp_path / "state" / "ag.db")
    run = store.get_run(result.run_id)
    assert run["status"] == "success" and run["rows"] == len(df)
    assert store.anomalies(result.run_id)
    assert ReviewQueue(tmp_path / "state" / "ag.db").counts()["pending"] > 0

    # second run: alert is deduplicated, review items are not duplicated
    pending = ReviewQueue(tmp_path / "state" / "ag.db").counts()["pending"]
    result2 = PipelineExecutor(cfg, console=False).run()
    assert result2.metrics["alerts_sent"] == 0
    assert ReviewQueue(tmp_path / "state" / "ag.db").counts()["pending"] == pending
    state = json.loads((tmp_path / "state" / "pipelines.json").read_text())
    assert state["orders_test"]["run_count"] == 2


def test_failed_run_is_recorded(tmp_path):
    cfg = PipelineConfig.load(write_pipeline(tmp_path, BASE))  # orders.csv does not exist
    result = run_pipeline(cfg, console=False)
    assert result.status == "failed" and "File not found" in result.error
    run = MetricsStore(tmp_path / "state" / "ag.db").get_run(result.run_id)
    assert run["status"] == "failed"


def test_incremental_sqlite_pipeline(tmp_path):
    db = tmp_path / "events.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE events (id INTEGER, value REAL)")
        conn.executemany(
            "INSERT INTO events VALUES (?, ?)", [(i, 10.0 + (i % 3)) for i in range(1, 101)]
        )
    body = """\
    name: events
    source: {type: sql, url: events.db, table: events, cursor: id}
    state: {incremental: true, dir: state}
    monitor: {db: state/ag.db}
    detectors: [mad]
    remediation: false
    alerts: {notifiers: []}
    """
    cfg = PipelineConfig.load(write_pipeline(tmp_path, body))
    r1 = PipelineExecutor(cfg, console=False).run()
    assert r1.metrics["rows"] == 100
    r2 = PipelineExecutor(cfg, console=False).run()
    assert r2.status == "empty" and r2.metrics["rows"] == 0
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO events VALUES (?, ?)", [(101, 10.0), (102, 500.0)])
    r3 = PipelineExecutor(cfg, console=False).run()
    assert r3.metrics["rows"] == 2


def test_config_validation_and_helpers(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="name"):
        PipelineConfig.from_dict({"source": {"type": "csv", "path": "x"}})
    with pytest.raises(ConfigError, match="source"):
        PipelineConfig.from_dict({"name": "x"})
    with pytest.raises(ConfigError, match="Unknown top-level"):
        PipelineConfig.from_dict({"name": "x", "source": {}, "detector": []})
    with pytest.raises(ConfigError, match="Bad detector"):
        PipelineConfig.from_dict({"name": "x", "source": {"path": "a.csv"}, "detectors": ["nope"]})
    with pytest.raises(ConfigError, match="remediation"):
        PipelineConfig.from_dict(
            {
                "name": "x",
                "source": {"path": "a.csv"},
                "remediation": {"default": {"missing": "guess"}},
            }
        )
    with pytest.raises(ConfigError, match="alert rule"):
        PipelineConfig.from_dict(
            {
                "name": "x",
                "source": {"path": "a.csv"},
                "alerts": {"rules": [{"metric": "m", "op": "~"}]},
            }
        )
    with pytest.raises(ConfigError, match="not found"):
        PipelineConfig.load(tmp_path / "missing.yaml")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        PipelineConfig.from_yaml("name: [unclosed")

    monkeypatch.setenv("AG_HOOK", "https://hooks.test/1")
    assert (
        expand_env("url: ${AG_HOOK} other: ${AG_MISSING:-dflt} none: ${AG_MISSING}")
        == "url: https://hooks.test/1 other: dflt none: "
    )
    assert (
        parse_duration("90") == 90
        and parse_duration("5m") == 300
        and parse_duration("1.5h") == 5400
    )
    with pytest.raises(ConfigError):
        parse_duration("soon")
    cfg = PipelineConfig.from_dict(
        {
            "name": "x",
            "source": {"path": "a.csv"},
            "schedule": {"every": "2m"},
            "detectors": "mad,iqr",
            "remediation": False,
        },
        base_dir=tmp_path,
    )
    assert (
        cfg.interval_seconds == 120 and cfg.detectors == ["mad", "iqr"] and cfg.remediation is None
    )
    assert cfg.resolve("data/a.csv") == tmp_path / "data" / "a.csv"


def test_templates_render_to_valid_configs(tmp_path):
    for name in TEMPLATES:
        text = render_template(name, name="t1", source="data.csv", group_by="region")
        data = yaml.safe_load(text)
        cfg = PipelineConfig.from_dict(data, base_dir=tmp_path)
        assert cfg.name == "t1" and cfg.interval_seconds
    assert "group_by: region" in render_template("csv_quality", source="x.csv", group_by="region")
    with pytest.raises(KeyError):
        render_template("nope")


def test_scheduler_runs_on_interval(tmp_path, orders):
    df, _ = orders
    df.head(200).to_csv(tmp_path / "orders.csv", index=False)
    cfg = PipelineConfig.load(write_pipeline(tmp_path, BASE))
    now = [0.0]
    slept = []

    def fake_sleep(s):
        slept.append(s)
        now[0] += s

    seen = []
    sched = Scheduler(
        [(cfg, 60.0)], max_runs=3, on_result=seen.append, sleep=fake_sleep, clock=lambda: now[0]
    )
    results = sched.run()
    assert len(results) == 3 and len(seen) == 3
    assert all(r.status == "success" for r in results)
    assert slept and all(abs(s - 60.0) < 1.0 for s in slept)
    with pytest.raises(ValueError):
        Scheduler([(cfg, 0)])
