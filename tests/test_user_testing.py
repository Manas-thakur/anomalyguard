"""Regressions found by using AnomalyGuard on a hand-made messy sales file."""

from __future__ import annotations

import pandas as pd

from anomalyguard.ingest.inference import EMAIL_PATTERN, infer_schema
from anomalyguard.schema.registry import Schema
from anomalyguard.schema.validator import SchemaValidator


def _sales(n: int = 60) -> pd.DataFrame:
    times = pd.date_range("2026-09-01", periods=n, freq="h").astype(str).tolist()
    emails = [f"user{i}@example.com" for i in range(n)]
    times[5] = "2031-01-01 10:00:00"  # in the future
    emails[7] = "not-an-email"
    return pd.DataFrame({"order_time": times, "customer_email": emails})


def test_inferred_schema_flags_future_timestamps_and_bad_emails():
    df = _sales()
    schema = infer_schema(df, "sales")
    assert schema.fields["order_time"].max == "now"
    assert schema.fields["customer_email"].pattern == EMAIL_PATTERN
    errors = SchemaValidator(schema).validate(df).errors
    by_rule = {(e.column, e.rule): e for e in errors}
    assert by_rule[("order_time", "max")].row == 5
    assert "in the future" in by_rule[("order_time", "max")].message
    assert by_rule[("customer_email", "pattern")].row == 7
    assert "not a valid email address" in by_rule[("customer_email", "pattern")].message
    assert len(errors) == 2


def test_now_constraint_survives_a_schema_round_trip(tmp_path):
    schema = infer_schema(_sales(), "sales")
    path = tmp_path / "sales.schema.yaml"
    schema.save(path)
    again = Schema.load(path)
    assert again.fields["order_time"].max == "now"
    assert len(SchemaValidator(again).validate(_sales()).errors) == 2


def test_no_constraints_inferred_when_data_does_not_support_them():
    future_heavy = pd.DataFrame(
        {"t": pd.date_range("2040-01-01", periods=20, freq="D").astype(str)}
    )
    assert infer_schema(future_heavy).fields["t"].max is None  # e.g. a schedule
    names = pd.DataFrame({"name": [f"Customer {i}" for i in range(20)]})
    assert infer_schema(names).fields["name"].pattern is None
