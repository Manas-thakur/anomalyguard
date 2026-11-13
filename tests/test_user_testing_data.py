"""Regressions from a hands-on QA pass over ingest, detection and remediation (v0.3.0)."""

from __future__ import annotations

import json
import logging
import sqlite3

import numpy as np
import pandas as pd
import pytest

import anomalyguard as ag
from anomalyguard.cli import main
from anomalyguard.detect import FlatlineDetector, RollingZScoreDetector, run_detectors
from anomalyguard.detect.base import fmt
from anomalyguard.ingest import CSVSource, infer_schema, read_any
from anomalyguard.ingest.files import sniff_delimiter
from anomalyguard.pipeline import PipelineConfig, PipelineExecutor
from anomalyguard.pipeline.sinks import write_frame
from anomalyguard.remediate import RemediationPipeline, RemediationPolicy, ReviewQueue
from anomalyguard.remediate.strategies import Cap
from anomalyguard.schema.coercion import coerce_series, parse_dates
from anomalyguard.schema.registry import DataType, Field, Schema
from anomalyguard.schema.validator import SchemaValidator

# ---------------------------------------------------------------- M1 NA tokens


def test_csv_keeps_na_text_and_reads_empty_cells_as_missing(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("region,price,note\nNA,1.5,None\nEU,,null\nN/A,3,x\n", encoding="utf-8")
    df = read_any(path)
    assert df["region"].tolist() == ["NA", "EU", "N/A"]
    assert df["note"].tolist() == ["None", "null", "x"]
    assert pd.api.types.is_float_dtype(df["price"]) and df["price"].isna().tolist() == [
        False,
        True,
        False,
    ]
    # opt in to extra missing-value tokens
    df = read_any(path, na_values=["NA", "N/A", "null"])
    assert df["region"].isna().sum() == 2 and df["note"].isna().sum() == 1


def test_fix_does_not_impute_north_america(tmp_path, capsys):
    path = tmp_path / "orders.csv"
    rows = ["id,region,amount"] + [f"{i},{'NA' if i % 2 else 'EU'},{10 + i % 5}" for i in range(40)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    out = tmp_path / "clean.csv"
    assert main(["fix", str(path), "-o", str(out)]) == 0
    clean = pd.read_csv(out, keep_default_na=False)
    assert (clean["region"] == "NA").sum() == 20
    schema = infer_schema(read_any(path))
    assert "NA" in schema.fields["region"].allowed
    assert SchemaValidator(schema).validate(read_any(path)).passed
    # CLI opt-in
    capsys.readouterr()
    assert main(["profile", str(path), "--na-values", "NA", "--json"]) == 0
    prof = json.loads(capsys.readouterr().out)
    region = next(c for c in prof["columns"] if c["name"] == "region")
    assert region["nulls"] == 20


# ------------------------------------------------------- M2 NaN / inf formatting


def test_validate_prints_not_null_violations(tmp_path, capsys):
    data = tmp_path / "d.csv"
    data.write_text("a,b\n1,x\n,y\n3,z\n", encoding="utf-8")
    schema = tmp_path / "s.yaml"
    schema.write_text(
        "fields:\n  a: {type: integer, nullable: false}\n  b: {type: string}\n", encoding="utf-8"
    )
    assert main(["validate", str(data), "--schema", str(schema)]) == 1
    out = capsys.readouterr().out
    assert "not_null" in out and "missing value in non-nullable column" in out


def test_infinite_values_are_invalid_not_a_crash(tmp_path, capsys):
    df = pd.DataFrame({"a": ["1", "2", "inf", "-inf", "3", "NaN"] * 10})
    values, failed = coerce_series(df["a"], DataType.FLOAT)
    assert failed.sum() == 20  # +-inf are invalid; "NaN" text is just missing
    assert not np.isinf(values.dropna()).any()
    assert fmt(float("inf")) == "inf" and fmt(-np.inf) == "-inf"
    path = tmp_path / "inf.csv"
    df.to_csv(path, index=False)
    for cmd in (["profile", str(path)], ["detect", str(path), "-m", "mad,iqr"]):
        assert main(cmd) == 0
    report = SchemaValidator(infer_schema(df)).validate(df)
    assert {e.message for e in report.errors if e.rule == "type"} == {
        "'inf' is not a finite number",
        "'-inf' is not a finite number",
    }
    # detectors never see inf
    res = run_detectors(pd.DataFrame({"x": [1.0, 2.0, np.inf, 3.0] * 10}), ["mad"])
    assert np.isfinite(res.results[0].raw_scores).all()


# ------------------------------------------------------------ M3 huge numbers


def test_huge_whole_numbers_are_floats(tmp_path):
    df = pd.DataFrame({"big": [1e18, 2e18, 3e18, 1e300] * 10, "n": range(40)})
    schema = infer_schema(df)
    assert schema.fields["big"].dtype == DataType.FLOAT
    assert schema.fields["n"].dtype == DataType.INTEGER
    values, failed = coerce_series(df["big"], DataType.INTEGER)  # a schema may say integer
    assert not failed.any() and values.dtype == float
    path = tmp_path / "huge.csv"
    df.to_csv(path, index=False)
    assert main(["fix", str(path), "-o", str(tmp_path / "out.csv")]) == 0


# ---------------------------------------------- M4 delimiters and encodings


def test_semicolon_file_with_decimal_commas(tmp_path):
    path = tmp_path / "eu.csv"
    rows = ["a;b"] + [f"{i},5;{i % 7},25" for i in range(50)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    df = read_any(path)
    assert list(df.columns) == ["a", "b"]
    assert df["a"].iloc[3] == pytest.approx(3.5) and df["b"].iloc[3] == pytest.approx(3.25)
    assert sniff_delimiter("x|y\n1|2\n3|4\n") == "|"
    assert sniff_delimiter("x\n1\n2\n") == ","


def test_explicit_wrong_delimiter_warns_and_extra_fields_do_not_become_an_index(tmp_path, caplog):
    path = tmp_path / "semi.csv"
    path.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="anomalyguard.ingest"):
        df = read_any(path, delimiter=",")
    assert list(df.columns) == ["a;b"]
    assert "delimiter is probably ';'" in caplog.text
    ragged = tmp_path / "ragged.csv"
    ragged.write_text("a,b\n1,2\n3,4,5\n", encoding="utf-8")
    with pytest.raises(Exception, match="--delimiter"):
        read_any(ragged)


def test_latin1_file_falls_back_with_a_warning(tmp_path, caplog, capsys):
    path = tmp_path / "latin1.csv"
    path.write_bytes("name,val\nJosé,1\nZoë,2\n".encode("latin-1"))
    with caplog.at_level(logging.WARNING, logger="anomalyguard.ingest"):
        df = read_any(path)
    assert df["name"].tolist() == ["José", "Zoë"]
    assert "not valid UTF-8" in caplog.text
    assert main(["profile", str(path), "--encoding", "latin-1"]) == 0
    assert main(["profile", str(path), "--sep", ";"]) == 0  # single column: still readable


def test_empty_and_header_only_files_are_errors(tmp_path, capsys):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    header = tmp_path / "header.csv"
    header.write_text("a,b\n", encoding="utf-8")
    assert main(["profile", str(empty)]) == 1
    assert "file is empty" in capsys.readouterr().err
    assert main(["profile", str(header)]) == 2
    assert "no data rows" in capsys.readouterr().err


def test_sqlite_without_table_lists_tables(tmp_path, capsys):
    db = tmp_path / "shop.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE orders (id INTEGER)")
        conn.execute("CREATE TABLE customers (id INTEGER)")
    conn.close()
    assert main(["profile", str(db)]) == 1
    err = capsys.readouterr().err
    assert "--table" in err and "customers, orders" in err


# ------------------------------------------------------- M5 group-aware capping


def _two_currencies(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    usd = np.round(rng.normal(100, 40, 200), 2)
    jpy = np.round(rng.normal(15000, 1500, 200), 2)
    df = pd.DataFrame({"region": ["US"] * 200 + ["JP"] * 200, "price": np.r_[usd, jpy]})
    df.loc[5, "price"] = 400.0  # moderately high for US: capped within US
    df.loc[205, "price"] = 23000.0  # moderately high for JP: capped within JP
    df.loc[7, "price"] = -150.0  # wrong sign: review
    return df


def test_cap_uses_group_fences_and_clamps_never_negative_columns():
    df = _two_currencies()
    report = ag.detect(df, ["mad"], group_by="region")
    result = RemediationPipeline({"dedupe": False}).run(df, report)
    out = result.data
    assert 100 < out.loc[5, "price"] < 400  # US range, not the global one
    assert 15000 < out.loc[205, "price"] < 23000  # JP range, never pulled to dollars
    jp_clean = out.loc[200:, "price"].drop(index=205)
    assert (jp_clean == df.loc[200:, "price"].drop(index=205)).all()
    assert out.loc[7, "price"] == -150.0
    note = next(f.reason for f in result.flagged if f.row == 7)
    assert "never negative" in note and "expected 0 to" in note and "region=US" in note
    caps = {c.row: c.reason for c in result.changes if c.strategy == "cap"}
    assert "for region=US" in caps[5] and "for region=JP" in caps[205]


def test_cap_small_group_falls_back_to_column_fences():
    s = pd.Series([10.0] * 3 + [11, 9, 10, 12, 8, 10, 11, 9, 10, 10, 11, 9, 10, 18.0])
    groups = pd.Series(["tiny"] * 3 + ["big"] * 13 + ["tiny"])
    df = pd.DataFrame({"v": s})
    mask = np.zeros(len(s), dtype=bool)
    mask[-1] = True
    cap = Cap(groups=groups, group_label="g")
    changes = cap.apply(df, "v", mask)
    assert len(changes) == 1 and "column range" in changes[0].reason


def test_integer_fences_round_outward():
    df = pd.DataFrame({"q": [3, 4, 4, 5, 3, 4, 5, 4, 3, 4, 4, 5, 10, 11]})
    mask = np.zeros(len(df), dtype=bool)
    mask[[12, 13]] = True
    cap = Cap(k=3.5)
    _lo, hi = cap.bounds(df["q"], mask)
    changes = cap.apply(df, "q", mask)
    upper = int(np.ceil(hi))
    assert all(c.after == upper for c in changes)
    if upper >= 10:  # a flagged value inside the rounded fence is left alone
        assert df.loc[12, "q"] == 10 and "within the capping range" in cap.skipped[12]


# --------------------------------------------- M7 incremental reference window


def _incremental(tmp_path, reference_rows: int | None = None) -> PipelineConfig:
    rng = np.random.default_rng(1)
    data = tmp_path / "data.csv"
    pd.DataFrame({"id": range(500), "amount": np.round(rng.normal(100, 10, 500), 2)}).to_csv(
        data, index=False
    )
    detection = {} if reference_rows is None else {"reference_rows": reference_rows}
    return PipelineConfig.from_dict(
        {
            "name": "inc",
            "source": {"type": "csv", "path": str(data)},
            "detectors": ["iqr"],
            "detection": detection,
            "remediation": False,
            "state": {"incremental": True, "dir": str(tmp_path / "state")},
            "monitor": {"enabled": False},
            "alerts": {"enabled": False},
        },
        base_dir=tmp_path,
    )


def test_incremental_batch_is_scored_against_earlier_rows(tmp_path):
    cfg = _incremental(tmp_path)
    assert PipelineExecutor(cfg, console=False).run().metrics["rows"] == 500
    with open(tmp_path / "data.csv", "a", encoding="utf-8") as fh:
        fh.write("500,101.5\n501,999999\n502,98.2\n")
    result = PipelineExecutor(cfg, console=False).run()
    assert result.metrics["rows"] == 3 and result.metrics["reference_rows"] == 500
    assert result.report.anomalous_rows == [1]
    ref = tmp_path / "state" / "inc.reference.jsonl"
    assert len(ref.read_text(encoding="utf-8").splitlines()) == 503
    from anomalyguard.pipeline.state import PipelineState

    PipelineState(tmp_path / "state").reset("inc")
    assert not ref.exists()


def test_small_batch_without_reference_warns(tmp_path, caplog):
    cfg = _incremental(tmp_path, reference_rows=0)
    PipelineExecutor(cfg, console=False).run()
    with open(tmp_path / "data.csv", "a", encoding="utf-8") as fh:
        fh.write("500,101.5\n501,999999\n502,98.2\n")
    with caplog.at_level(logging.WARNING, logger="anomalyguard.pipeline"):
        result = PipelineExecutor(cfg, console=False).run()
    assert "only 3 new rows" in caplog.text
    assert any("only 3 new rows" in w for w in result.metrics["warnings"])
    with pytest.raises(ValueError, match="reference_rows"):
        _incremental(tmp_path, reference_rows=-1)


# ------------------------------------------------------------- M8 time series


def _hourly(n: int = 24 * 30, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-03-01", periods=n, freq="h")
    temp = 20 + 5 * np.sin(2 * np.pi * (t.hour.to_numpy() - 9) / 24) + rng.normal(0, 0.3, n)
    temp[400] += 15
    return pd.DataFrame({"timestamp": t.astype(str), "temperature": np.round(temp, 2)})


def test_gaps_do_not_shift_the_seasonal_phase(caplog):
    full = _hourly()
    gapped = full.drop(index=range(200, 213)).reset_index(drop=True)  # 13 hours missing
    with caplog.at_level(logging.WARNING, logger="anomalyguard.detect"):
        rep = run_detectors(gapped, ["seasonal"], columns=["temperature"], time_column="timestamp")
    assert "1 gap(s)" in caplog.text and "regular 01:00:00 grid" in caplog.text
    assert rep.warnings and "13 missing points" in rep.warnings[0]
    flagged = set(gapped.loc[rep.anomalous_rows, "timestamp"])
    assert full.loc[400, "timestamp"] in flagged
    # by row position the phase shifts by 13 hours after the gap: most of the
    # series looks anomalous
    by_row = run_detectors(gapped, ["seasonal"], columns=["temperature"])
    assert by_row.n_anomalies > 4 * rep.n_anomalies


def test_rolling_zscore_after_a_stuck_period_and_flatline():
    df = _hourly()
    df.loc[300:329, "temperature"] = df.loc[299, "temperature"]  # stuck sensor
    df.loc[400, "temperature"] -= 15  # undo the spike: only the stuck run is abnormal
    roll = RollingZScoreDetector(window=6, columns=["temperature"]).fit_detect(df)
    assert not set(np.flatnonzero(roll.labels)) & set(range(330, 340))
    flat = FlatlineDetector(columns=["temperature"]).fit_detect(df)
    assert set(np.flatnonzero(flat.labels)) == set(range(299, 330))
    assert "repeated for 31 consecutive points" in flat.findings[0].reason
    assert ag.detect(df, ["stuck"], columns=["temperature"]).n_anomalies == 31


def test_time_column_errors(tmp_path, capsys):
    path = tmp_path / "s.csv"
    _hourly(500).to_csv(path, index=False)
    assert main(["detect", str(path), "--time-column", "nope"]) == 1
    assert "Time column 'nope' not found" in capsys.readouterr().err
    assert main(["detect", str(path), "-m", ""]) == 2
    assert "-m/--method is empty" in capsys.readouterr().err


# ------------------------------------------- M9 invalid policy vs outlier fixing


@pytest.mark.parametrize("invalid", ["flag", "drop", "keep"])
def test_invalid_policy_does_not_disable_outlier_fixing(invalid):
    vals = [str(v) for v in [10, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 4] + ["18", "oops"]
    df = pd.DataFrame({"v": vals})
    report = ag.detect(df, ["mad"])
    policy = {"default": {"invalid": invalid}, "dedupe": False}
    result = RemediationPipeline(policy, schema=infer_schema(df)).run(df, report)
    caps = [c for c in result.changes if c.strategy == "cap"]
    assert len(caps) == 1 and caps[0].row == 40 and caps[0].before == "18"
    assert float(result.data["v"].iloc[40]) < 18
    if invalid == "keep":
        assert result.data["v"].iloc[41] == "oops"


# ------------------------------------------------------------ minor: remediation


def test_future_dates_are_flagged_not_invented():
    t = pd.date_range("2026-01-01", periods=30, freq="D").astype(str).tolist()
    t[3] = "2031-05-01 00:00:00"
    df = pd.DataFrame({"t": t})
    schema = infer_schema(df)
    assert schema.fields["t"].max == "now"
    result = RemediationPipeline(schema=schema).run(df)
    item = next(f for f in result.flagged if f.column == "t")
    assert item.row == 3 and "future" in item.reason
    assert str(result.data["t"].iloc[3]).startswith("2031")


def test_ambiguous_day_month_order():
    s = pd.Series(["13/01/2026", "11/01/2026", "2026-02-03"], name="d")
    out, ambiguous = parse_dates(s)
    assert out.iloc[1] == pd.Timestamp("2026-01-11") and not ambiguous.any()
    both = pd.Series(["13/01/2026", "01/13/2026", "03/04/2026"], name="e")
    out, ambiguous = parse_dates(both)
    assert ambiguous.tolist() == [False, False, True] and pd.isna(out.iloc[2])


def test_cell_changed_twice_keeps_the_original_value():
    df = pd.DataFrame({"v": [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3 + [17.0]})
    schema = Schema(name="t", fields={"v": Field("v", DataType.FLOAT, max=12)})
    result = RemediationPipeline({"dedupe": False}, schema=schema).run(df, ag.detect(df, ["mad"]))
    (change,) = [c for c in result.changes if c.row == 30]
    assert change.before == 17.0 and change.after == 12 and change.strategy == "cap+clip"
    assert result.data["v"].iloc[30] == 12


def test_flagged_cells_are_not_rewritten_by_later_steps():
    df = pd.DataFrame({"v": [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3 + [-50.0]})
    schema = Schema(name="t", fields={"v": Field("v", DataType.FLOAT, min=0)})
    result = RemediationPipeline({"dedupe": False}, schema=schema).run(df, ag.detect(df, ["mad"]))
    item = next(f for f in result.flagged if f.row == 30)
    assert item.value == -50.0 == result.data["v"].iloc[30]


def test_json_report_says_when_changes_are_truncated():
    df = pd.DataFrame({"v": [1.0, None] * 30})
    result = RemediationPipeline({"dedupe": False}).run(df)
    data = result.report().to_dict(max_changes=10)
    assert data["total_changes"] == 30 and data["truncated"] and len(data["changes"]) == 10


def test_missing_policies_never_invent_ids_or_numbers_for_text():
    df = pd.DataFrame(
        {
            "order_id": [1, 2, None, 4, 5, 6],
            "city": ["a", None, "b", "a", "b", "a"],
            "v": [1.0, 2, 3, None, 5, 6],
        }
    )
    for method in ("mean", "median", "interpolate", "mode", "ffill", "bfill"):
        result = RemediationPipeline({"default": {"missing": method}, "dedupe": False}).run(df)
        flagged = {f.column for f in result.flagged}
        assert "order_id" in flagged, method
        assert result.data["order_id"].isna().sum() == 1
        if method in ("mean", "median", "interpolate"):
            assert "city" in flagged and result.data["city"].isna().sum() == 1
        assert result.data["v"].isna().sum() == 0
    with pytest.raises(ValueError, match="constant needs a fill value"):
        RemediationPolicy.from_dict({"default": {"missing": "constant"}})
    with pytest.raises(ValueError, match="clip needs a range"):
        RemediationPolicy.from_dict({"default": {"outlier": "clip"}})


def test_fix_cli_constant_and_clip(tmp_path, capsys):
    path = tmp_path / "d.csv"
    pd.DataFrame({"v": [1.0, None, 3, 4, 5, 6, 7, 8, 9, 100]}).to_csv(path, index=False)
    out = tmp_path / "o.csv"
    assert main(["fix", str(path), "-o", str(out), "--outlier", "clip"]) == 2
    assert "clip needs a range" in capsys.readouterr().err
    assert main(["fix", str(path), "-o", str(out), "--missing", "constant"]) == 2
    assert (
        main(
            [
                "fix",
                str(path),
                "-o",
                str(out),
                "--missing",
                "constant",
                "--missing-value",
                "0",
                "--outlier",
                "clip",
                "--max",
                "10",
            ]
        )
        == 0
    )
    clean = pd.read_csv(out)
    assert clean["v"].iloc[1] == 0 and clean["v"].max() <= 10


def test_llm_auto_applied_items_are_marked_applied(tmp_path):
    from anomalyguard.remediate.llm import Suggestion

    class Fake:
        def suggest(self, record, column, value, reason):
            return Suggestion(value=12.0, confidence=0.95, rationale="typo")

    df = pd.DataFrame({"v": [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3 + [5000.0]})
    pipe = RemediationPipeline({"dedupe": False}, llm=Fake(), llm_auto_apply=True)
    result = pipe.run(df, ag.detect(df, ["mad"]))
    assert result.data["v"].iloc[30] == 12.0
    assert [f.applied for f in result.flagged] == [True]
    q = ReviewQueue(tmp_path / "r.db")
    (item_id,) = q.add_flagged(result.flagged, pipeline="p")
    item = q.get(item_id)
    assert item["status"] == "applied" and item["resolved_value"] == 12.0


# ----------------------------------------------------------- minor: detection


def test_lognormal_columns_are_scored_on_a_log_scale():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"x": rng.lognormal(3, 0.6, 4000)})
    for method in ("mad", "iqr"):
        rate = ag.detect(df, [method]).anomaly_rate
        assert rate < 0.03, (method, rate)
        linear = ag.detect(df, [{"method": method, "log_scale": False}]).anomaly_rate
        assert linear > 2 * rate
    df.loc[0, "x"] = 1e6
    rep = ag.detect(df, ["mad"])
    assert 0 in rep.anomalous_rows and "log scale" in rep.findings[0].reason


def test_vote_with_too_few_detectors_is_clamped(caplog):
    df = pd.DataFrame({"v": [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3 + [500.0]})
    with caplog.at_level(logging.WARNING, logger="anomalyguard.detect"):
        rep = run_detectors(df, ["mad"], combine="vote", min_votes=2)
        assert rep.n_anomalies == 1 and "single detector" in caplog.text
        rep = run_detectors(df, ["mad", "iqr"], combine="vote", min_votes=5)
    assert rep.n_anomalies == 1 and rep.min_votes == 2 and "using min_votes=2" in caplog.text


def test_cli_params_group_by_lists_and_ensemble(tmp_path, capsys):
    df = _two_currencies()
    df["channel"] = ["web", "shop"] * 200
    path = tmp_path / "g.csv"
    df.to_csv(path, index=False)
    out = tmp_path / "r.json"
    assert (
        main(["detect", str(path), "-m", "mad", "--group-by", "region,channel", "-o", str(out)])
        == 0
    )
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert "grouped(mad by region,channel)" in rep["summary"]["detectors"]
    assert (
        main(["detect", str(path), "-m", "mad", "--param", "mad.threshold=50", "-o", str(out)]) == 0
    )
    assert json.loads(out.read_text(encoding="utf-8"))["thresholds"]["mad"] == 50
    assert main(["detect", str(path), "-m", "mad", "--param", "seasonal.period=24"]) == 2
    assert "not one of the detectors" in capsys.readouterr().err
    assert main(["detect", str(path), "-m", "ensemble"]) == 1
    assert "ensemble needs member detectors" in capsys.readouterr().err
    args = ["detect", str(path), "-m", "ensemble", "--param", "ensemble.detectors=mad,iqr"]
    assert main([*args, "--param", "ensemble.combine=vote", "-o", str(out)]) == 0
    assert "ensemble[vote](mad,iqr)" in json.loads(out.read_text(encoding="utf-8"))["thresholds"]
    assert main(["detect", str(path), "-m", "mad", "--show-ids"]) == 0
    assert "All findings" in capsys.readouterr().out


def test_cli_applies_tuned_thresholds(tmp_path, capsys):
    from anomalyguard.monitor.store import MetricsStore

    path = tmp_path / "d.csv"
    pd.DataFrame({"v": [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3 + [30.0]}).to_csv(
        path, index=False
    )
    db = tmp_path / "state.db"
    store = MetricsStore(db)
    store.set_threshold("mad", 100.0)
    out = tmp_path / "r.json"
    assert main(["detect", str(path), "-m", "mad", "--db", str(db), "-o", str(out)]) == 0
    assert "Using tuned thresholds" in capsys.readouterr().err
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["n_anomalies"] == 0
    args = ["detect", str(path), "-m", "mad", "--db", str(db), "--no-tuned-thresholds"]
    assert main([*args, "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["n_anomalies"] == 1


# ---------------------------------------------------------------- minor: misc


def test_demo_generate_validates_rows_and_extension(tmp_path, capsys):
    assert main(["demo", "generate", "-n", "0", "-o", str(tmp_path / "a.csv")]) == 2
    assert main(["demo", "generate", "-n", "-5", "-o", str(tmp_path / "a.csv")]) == 2
    assert main(["demo", "generate", "-n", "5", "-o", str(tmp_path / "a.xlsx")]) == 2
    err = capsys.readouterr().err
    assert "at least 1" in err and ".xlsx" in err
    assert main(["demo", "generate", "-n", "5", "-o", str(tmp_path / "a.jsonl")]) == 0
    with pytest.raises(ValueError, match="unsupported file type"):
        write_frame(pd.DataFrame({"a": [1]}), tmp_path / "x.xlsx")


def test_csv_source_options_from_pipeline_config(tmp_path):
    path = tmp_path / "d.txt"
    path.write_text("a|b\nNA|1\nnull|2\n", encoding="utf-8")
    src = CSVSource(path, na_values="null", read_options={"na_values": ["n/a"]})
    df = src.read()
    assert df["a"].tolist()[0] == "NA" and pd.isna(df["a"].iloc[1])
    assert src.delimiter == "|" and src.encoding == "utf-8-sig"


def test_web_upload_and_cleaned_file_keep_na_text(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from anomalyguard.monitor.api import create_app
    from anomalyguard.monitor.settings import ServerSettings

    monkeypatch.chdir(tmp_path)
    rows = ["id,region,amount"] + [
        f"{i},{'NA' if i % 2 else 'EU'},{900 if i == 7 else 10 + i % 5}" for i in range(60)
    ]
    data = ("\n".join(rows) + "\n").encode("utf-8")
    settings = ServerSettings(pipeline_dirs=[tmp_path / "pipelines"], max_upload_mb=5)
    with TestClient(create_app(tmp_path / "state" / "ag.db", settings)) as client:
        meta = client.post("/api/datasets", files={"file": ("na.csv", data, "text/csv")}).json()
        profile = client.get(f"/api/datasets/{meta['id']}/profile").json()
        region = next(c for c in profile["columns"] if c["name"] == "region")
        assert region["nulls"] == 0
        body = {"dataset_id": meta["id"], "detectors": ["mad"]}
        aid = client.post("/api/analyses?wait=true", json=body).json()["analysis"]["id"]
        client.post(f"/api/analyses/{aid}/remediate", json={"default": {"outlier": "flag"}})
        client.post(f"/api/analyses/{aid}/review")
        (item,) = client.get("/api/review?column=amount").json()
        client.post(f"/api/review/{item['id']}/approve", json={"value": 11})
        applied = client.post("/api/review/bulk", json={"action": "apply", "ids": [item["id"]]})
        assert applied.json()["applied"] == 1
        cleaned = client.get(f"/api/analyses/{aid}/download/cleaned.csv").text
    lines = cleaned.strip().splitlines()
    assert sum(",NA," in ln for ln in lines) == 30 and "7,NA,11" in lines


def test_web_remediation_from_stored_findings_is_group_aware():
    from anomalyguard.monitor.workspace import rebuild_report

    df = _two_currencies()
    report = ag.detect(df, ["mad"], group_by="region")
    stored = [f.to_dict() for f in report.findings]
    rebuilt = rebuild_report(len(df), stored, list(df.index))
    assert rebuilt.groups == {"grouped(mad by region)": ["region"]}
    out = RemediationPipeline({"dedupe": False}).run(df, rebuilt).data
    assert 15000 < out.loc[205, "price"] < 23000


def test_group_keys_handle_missing_values_on_every_pandas_version():
    import pandas as pd

    from anomalyguard.detect.contextual import group_keys

    df = pd.DataFrame({"region": ["EU", None, "JP"], "cat": ["Home", "Toys", None]})
    assert group_keys(df, ["region", "cat"]).tolist() == ["EU|Home", "nan|Toys", "JP|nan"]
    assert group_keys(df, "region").tolist() == ["EU", "nan", "JP"]
