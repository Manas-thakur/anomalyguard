from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from anomalyguard.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "anomalyguard" in capsys.readouterr().out


def test_profile_and_validate(tmp_path, orders_csv, capsys):
    schema_path = tmp_path / "schema.yaml"
    assert main(["profile", orders_csv, "--schema-out", str(schema_path)]) == 0
    out = capsys.readouterr().out
    assert "Quality score" in out and "unit_price" in out and schema_path.exists()
    assert main(["profile", orders_csv, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["quality"]["n_rows"] > 0
    # the inferred schema marks order_id unique, so duplicates fail validation
    assert main(["validate", orders_csv, "--schema", str(schema_path)]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_detect(tmp_path, orders_csv, capsys):
    out_json = tmp_path / "report.json"
    code = main(
        [
            "detect",
            orders_csv,
            "-m",
            "mad,iqr",
            "--group-by",
            "region",
            "-o",
            str(out_json),
            "--top",
            "3",
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "anomalous" in text and "[region=" in text
    report = json.loads(out_json.read_text())
    assert report["summary"]["n_anomalies"] > 0
    assert main(["detect", orders_csv, "--fail-on-anomalies", "--json"]) == 1
    json.loads(capsys.readouterr().out)
    assert main(["detect", orders_csv, "--contamination", "0.05", "-m", "zscore"]) == 0


def test_fix(tmp_path, orders_csv, capsys):
    out = tmp_path / "clean.csv"
    report = tmp_path / "fix.md"
    review_db = tmp_path / "review.db"
    code = main(
        [
            "fix",
            orders_csv,
            "-o",
            str(out),
            "--report",
            str(report),
            "--group-by",
            "region",
            "--review-db",
            str(review_db),
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "cells fixed" in text
    clean = pd.read_csv(out)
    raw = pd.read_csv(orders_csv)
    assert len(clean) < len(raw)
    assert "# Remediation report" in report.read_text()
    assert main(["review", "list", "--db", str(review_db)]) == 0
    assert "pending" in capsys.readouterr().out
    assert main(["review", "approve", "1", "--value", "42", "--db", str(review_db)]) == 0
    assert "approved" in capsys.readouterr().out
    assert main(["review", "reject", "999", "--db", str(review_db)]) == 1


def test_init_and_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    shutil.copy(EXAMPLES / "data" / "orders.csv", tmp_path / "data" / "orders.csv")
    assert (
        main(["init", "--source", "data/orders.csv", "--name", "orders", "--group-by", "region"])
        == 0
    )
    assert Path("pipeline.yaml").exists()
    assert main(["init"]) == 1  # refuses to overwrite
    capsys.readouterr()
    assert main(["run", "pipeline.yaml"]) == 0
    out = capsys.readouterr().out
    assert "[orders] run #1" in out
    assert Path("out/orders_clean.csv").exists()
    assert Path(".anomalyguard/anomalyguard.db").exists()
    assert main(["run", "pipeline.yaml", "--every", "1s", "--max-runs", "1", "--json"]) == 0
    assert main(["feedback", "stats"]) == 0
    assert main(["feedback", "fp", "--anomaly-id", "1"]) == 0
    assert main(["feedback", "tune"]) == 0
    assert main(["init", "--list"]) == 0


def test_run_examples_pipeline(tmp_path, monkeypatch, capsys):
    work = tmp_path / "examples"
    shutil.copytree(EXAMPLES, work, ignore=shutil.ignore_patterns("out"))
    monkeypatch.chdir(tmp_path)
    assert main(["run", "examples/pipeline.yaml", "examples/sensor_pipeline.yaml"]) == 0
    out = capsys.readouterr().out
    assert "[orders_quality] run #1" in out and "[sensor_monitor] run #2" in out
    assert (tmp_path / "out" / "orders_clean.csv").exists()


def test_demo_commands(tmp_path, capsys):
    out = tmp_path / "s.csv"
    assert main(["demo", "generate", "-d", "sensor", "-n", "480", "-o", str(out)]) == 0
    assert out.exists() and (tmp_path / "s_labels.csv").exists()
    assert main(["demo", "benchmark", "--datasets", "sensor", "-o", str(tmp_path / "b.md")]) == 0
    assert "### sensor" in (tmp_path / "b.md").read_text()
    assert main(["detectors"]) == 0
    assert "iforest" in capsys.readouterr().out


def test_errors_are_reported(capsys):
    assert main(["detect", "does-not-exist.csv"]) == 1
    assert "error:" in capsys.readouterr().err


def test_doctor(tmp_path, capsys):
    db = tmp_path / "state" / "ag.db"
    pdir = tmp_path / "pipelines"
    pdir.mkdir()
    shutil.copy(EXAMPLES / "pipeline.yaml", pdir / "pipeline.yaml")
    (pdir / "broken.yaml").write_text("name: broken\nsource: {type: csv}\nnope: 1\n")
    assert main(["doctor", "--db", str(db), "--pipeline-dir", str(pdir)]) == 0
    out = capsys.readouterr().out
    assert "AnomalyGuard" in out and "Extras" in out and "orders_quality" in out
    assert "invalid pipeline" in out and "ANOMALYGUARD_API_KEY" in out
    assert not db.exists()  # doctor does not create the database
    assert main(["doctor", "--db", str(db), "--pipeline-dir", str(pdir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"]["writable"] and data["extras"]["server"]["installed"]
    assert any(not p["valid"] for p in data["pipelines"]) and data["problems"]
