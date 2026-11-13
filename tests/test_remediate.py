from __future__ import annotations

import json

import httpx
import numpy as np
import pandas as pd
import pytest

import anomalyguard as ag
from anomalyguard.detect import run_detectors
from anomalyguard.ingest import infer_schema
from anomalyguard.remediate import (
    Cap,
    Clip,
    ColumnPolicy,
    Impute,
    LLMSuggester,
    RemediationPipeline,
    RemediationPolicy,
    ReviewQueue,
    SetNull,
    TypeFix,
    Winsorize,
    parse_suggestion,
)


def test_impute_methods():
    base = pd.DataFrame({"v": [1.0, np.nan, 3.0, np.nan, 100.0], "c": ["a", None, "a", "b", None]})
    for method, expected in [
        ("mean", 35),
        ("median", 3),
        ("ffill", 1),
        ("bfill", 3),
        ("interpolate", 2),
    ]:
        df = base.copy()
        changes = Impute(method).apply(df, "v", df["v"].isna().to_numpy())
        assert df["v"].iloc[1] == pytest.approx(expected), method
        assert len(changes) == 2 and changes[0].strategy == f"impute_{method}"
    df = base.copy()
    Impute("mode").apply(df, "c", df["c"].isna().to_numpy())
    assert df["c"].tolist() == ["a", "a", "a", "b", "a"]
    df = base.copy()
    Impute("constant", value=0).apply(df, "v", df["v"].isna().to_numpy())
    assert df["v"].isna().sum() == 0
    with pytest.raises(ValueError):
        Impute("magic")


def test_cap_winsorize_clip_setnull():
    vals = [10.0, 11, 9, 10, 12, 8, 10, 11, 9, 500]
    df = pd.DataFrame({"v": vals})
    mask = np.array([False] * 9 + [True])
    ch = Cap(k=3.5).apply(df, "v", mask)
    assert len(ch) == 1 and 10 < df["v"].iloc[-1] < 20
    df = pd.DataFrame({"v": vals})
    Winsorize(0.0, 0.8).apply(df, "v", mask)
    assert df["v"].iloc[-1] <= 12
    df = pd.DataFrame({"v": [-5.0, 5, 50]})
    Clip(0, 10).apply(df, "v", np.array([True, False, True]))
    assert df["v"].tolist() == [0, 5, 10]
    df = pd.DataFrame({"v": [1, 2, 3]})
    SetNull().apply(df, "v", np.array([False, True, False]))
    assert df["v"].isna().tolist() == [False, True, False]


def test_type_fix():
    df = pd.DataFrame({"v": ["1", "2", "oops", "4"]})
    ch = TypeFix("integer").apply(df, "v")
    assert len(ch) == 1 and ch[0].before == "oops" and ch[0].after is None
    assert df["v"].isna().sum() == 1


def test_policy_parsing_and_validation():
    pol = RemediationPolicy.from_dict(
        {"default": {"missing": "median"}, "columns": {"a": {"outlier": "flag"}}, "dedupe": ["id"]}
    )
    assert pol.for_column("a").outlier == "flag"
    assert pol.for_column("a").missing == "median"  # inherits default
    assert pol.for_column("b").outlier == "cap"
    with pytest.raises(ValueError):
        ColumnPolicy(missing="guess")
    with pytest.raises(ValueError):
        RemediationPolicy.from_dict({"unknown": 1})


def test_pipeline_end_to_end_on_orders(orders):
    df, labels = orders
    schema = infer_schema(df, name="orders")
    report = ag.detect(
        df, ["mad"], schema=schema, columns=["quantity", "unit_price", "delivery_days"]
    )
    result = RemediationPipeline(schema=schema).run(df, report)
    out = result.data
    n_dup = int((labels["anomaly_type"] == "duplicate").sum())
    assert len(out) == len(df) - n_dup
    assert not out.duplicated(subset=["order_id"]).any()
    # type errors and missing numbers are fixed, ids kept
    assert pd.api.types.is_numeric_dtype(out["unit_price"])
    for col in ("quantity", "unit_price", "delivery_days", "region"):
        assert out[col].isna().sum() == 0, col
    # point outliers in quantity are capped
    assert out["quantity"].max() < 50
    strategies = {c.strategy for c in result.changes}
    assert {"type_fix", "cap", "impute_median", "impute_mode"} <= strategies
    # the original frame is untouched
    assert df["quantity"].max() >= 150
    rep = result.report()
    s = rep.summary()
    assert s["rows_dropped"] == n_dup and s["cells_changed"] == result.n_changed_cells
    md = rep.to_markdown()
    assert "# Remediation report" in md and "## Cell changes" in md and "## Dropped rows" in md
    data = json.loads(rep.to_json())
    assert data["summary"]["rows_in"] == len(df)
    assert not rep.diff().empty


def test_contextual_outliers_go_to_review(orders):
    df, labels = orders
    report = ag.detect(df, [{"method": "mad", "group_by": "region", "columns": ["unit_price"]}])
    result = RemediationPipeline().run(df, report)
    ctx_rows = set(np.flatnonzero(labels["anomaly_type"].eq("contextual").to_numpy()))
    flagged_rows = {f.row for f in result.flagged if f.column == "unit_price"}
    assert len(ctx_rows & flagged_rows) >= 0.8 * len(ctx_rows)


def test_flag_and_drop_policies():
    df = pd.DataFrame(
        {"id": [1, 2, 3, 4, 5, 6, 7, 8], "v": [10.0, 11, 9, 10, 1000, 11, np.nan, 10]}
    )
    report = run_detectors(df, ["mad"], columns=["v"])
    pol = {"default": {"outlier": "drop", "missing": "flag"}, "flag_column": "needs_review"}
    res = RemediationPipeline(pol).run(df, report)
    assert 4 not in res.data.index  # dropped outlier row (label 4)
    assert res.data.loc[6, "needs_review"]
    assert any(f.column == "v" and f.reason == "missing value" for f in res.flagged)
    pol = {"default": {"outlier": "median"}}
    res = RemediationPipeline(pol).run(df, report)
    assert res.data.loc[4, "v"] == 10


def test_unattributed_rows_and_integer_restore():
    df = pd.DataFrame(
        {"a": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] * 3, "b": [2, 4, 6, 8, 10, 12, 14, 16, 18, 20] * 3}
    )
    df.loc[5, "b"] = 1  # breaks the a/b relationship but stays in range
    df.loc[7, "a"] = np.nan
    report = run_detectors(df, [{"method": "knn", "threshold": 0.5}])
    res = RemediationPipeline({"unattributed": "flag"}).run(df, report)
    assert any(f.column is None for f in res.flagged)
    assert str(res.data["a"].dtype) == "Int64"


def test_review_queue(tmp_path):
    q = ReviewQueue(tmp_path / "review.db")
    a = q.add(
        "price",
        999.0,
        "too high",
        row_index=3,
        pipeline="p",
        suggestion=99.0,
        suggestion_confidence=0.9,
    )
    b = q.add("qty", -1, "negative", row_index=5, pipeline="p")
    assert q.counts() == {"pending": 2, "approved": 0, "rejected": 0, "applied": 0}
    assert q.approve(a)["resolved_value"] == 99.0  # defaults to the suggestion
    assert q.reject(b, note="real refund")["status"] == "rejected"
    assert q.counts()["approved"] == 1
    assert [i["id"] for i in q.list(status="pending")] == []
    df = pd.DataFrame({"price": [1.0] * 6, "qty": [1] * 6})
    out, n = q.apply(df)
    assert n == 1 and out.loc[3, "price"] == 99.0
    with pytest.raises(KeyError):
        q.approve(12345)
    # re-adding the same pending item is a no-op
    c = q.add("x", 1, "r", row_index=1, pipeline="p")
    ids = q.add_flagged([{"column": "x", "value": 1, "reason": "r", "index": 1}], pipeline="p")
    assert ids == [c]


def test_parse_suggestion():
    s = parse_suggestion('Sure! {"value": 42, "confidence": 1.7, "rationale": "median"} done')
    assert s.value == 42 and s.confidence == 1.0
    assert parse_suggestion("no json here") is None
    assert parse_suggestion('{"confidence": 0.5}') is None


def test_llm_suggester_ollama_and_openai():
    def ollama(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/generate" and body["format"] == "json"
        assert "unit_price" in body["prompt"]
        assert (
            "Current value: 900.5" + chr(10) in body["prompt"]
        )  # numpy scalars read as plain numbers
        return httpx.Response(
            200,
            json={
                "response": '{"value": 19.5, "confidence": 0.9, "rationale": "typical north price"}'
            },
        )

    llm = LLMSuggester("ollama", transport=httpx.MockTransport(ollama))
    s = llm.suggest(
        {"region": "north", "unit_price": 900.5}, "unit_price", np.float64(900.5), "outlier"
    )
    assert s.value == 19.5 and s.confidence == 0.9

    def openai(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"value": "north", "confidence": 0.6}'}}]},
        )

    llm = LLMSuggester(
        "openai", base_url="http://localhost:9999/v1", transport=httpx.MockTransport(openai)
    )
    assert llm.suggest({}, "region", None, "missing").value == "north"
    with pytest.raises(ValueError):
        LLMSuggester("other")


def test_pipeline_uses_llm_for_flagged_items():
    class FakeLLM:
        def suggest(self, record, column, value, reason):
            from anomalyguard.remediate import Suggestion

            return Suggestion(10.0, 0.95, "neighbours are ~10")

    df = pd.DataFrame({"v": [10.0, 11, 9, 10, 1000, 11, 10, 10]})
    report = run_detectors(df, ["mad"], columns=["v"])
    res = RemediationPipeline(
        {"default": {"outlier": "flag"}}, llm=FakeLLM(), llm_auto_apply=True
    ).run(df, report)
    assert res.flagged[0].suggestion == 10.0
    assert res.data.loc[4, "v"] == 10.0
    assert any(c.strategy == "llm" for c in res.changes)

    class BrokenLLM:
        def suggest(self, *a):
            raise httpx.ConnectError("down")

    res = RemediationPipeline({"default": {"outlier": "flag"}}, llm=BrokenLLM()).run(df, report)
    assert "LLM unavailable" in res.flagged[0].suggestion_rationale


def test_fix_api(orders):
    df, _ = orders
    res = ag.fix(df, columns=["quantity", "unit_price", "delivery_days"])
    assert res.data["quantity"].max() < 50
