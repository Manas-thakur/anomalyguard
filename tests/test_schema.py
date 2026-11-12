from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from anomalyguard.schema import (
    DataType,
    Field,
    Schema,
    SchemaRegistry,
    SchemaValidator,
    TypeCoercer,
    coerce_frame,
    coerce_series,
    compute_quality,
)


def make_schema() -> Schema:
    return Schema(
        name="people",
        primary_key=["id"],
        fields={
            "id": Field("id", DataType.INTEGER, nullable=False, unique=True),
            "age": Field("age", DataType.INTEGER, min=0, max=120),
            "email": Field("email", DataType.STRING, pattern=r"[^@]+@[^@]+\.\w+"),
            "code": Field("code", DataType.STRING, min_length=2, max_length=3),
            "tier": Field("tier", DataType.CATEGORICAL, allowed=["gold", "silver"]),
            "active": Field("active", DataType.BOOLEAN),
            "joined": Field("joined", DataType.DATETIME, min="2000-01-01"),
        },
    )


def test_schema_yaml_json_roundtrip(tmp_path):
    schema = make_schema()
    for name in ("s.yaml", "s.json"):
        path = schema.save(tmp_path / name)
        loaded = Schema.load(path)
        assert loaded.to_dict() == schema.to_dict()
    assert (
        Schema.from_dict({"name": "x", "fields": [{"name": "a", "type": "float"}]})
        .fields["a"]
        .dtype
        == DataType.FLOAT
    )
    assert Schema.from_dict({"fields": {"a": "integer"}}).fields["a"].dtype == DataType.INTEGER
    with pytest.raises(ValueError):
        Field.from_dict("a", {"type": "integer", "bogus": 1})


def test_registry_versions(tmp_path):
    reg = SchemaRegistry(tmp_path)
    s = make_schema()
    assert reg.register(s).version == 1
    s.fields["age"].max = 150
    assert reg.register(s).version == 2
    assert reg.versions("people") == [1, 2]
    assert reg.get("people").fields["age"].max == 150
    assert reg.get("people", 1).fields["age"].max == 120
    assert reg.names() == ["people"]
    with pytest.raises(KeyError):
        reg.get("nobody")


def test_validator_catches_each_rule():
    df = pd.DataFrame(
        {
            "id": [1, 2, 2, None],
            "age": ["30", "abc", "-1", "200"],
            "email": ["a@b.com", "bad", None, "c@d.org"],
            "code": ["AB", "A", "ABCD", "XYZ"],
            "tier": ["gold", "bronze", "silver", None],
            "active": ["yes", "no", "maybe", "true"],
            "joined": ["2020-01-01", "1990-05-05", "not a date", None],
        }
    )
    rep = SchemaValidator(make_schema()).validate(df)
    rules = rep.counts_by_rule()
    assert rules["type"] == 3  # 'abc' age, 'maybe' active, 'not a date'
    assert rules["min"] == 2  # age -1, joined 1990
    assert rules["max"] == 1
    assert rules["not_null"] == 1
    assert rules["unique"] == 2
    assert rules["primary_key"] == 1
    assert rules["pattern"] == 1
    assert rules["min_length"] == 1 and rules["max_length"] == 1
    assert rules["allowed"] == 1
    assert not rep.passed
    assert rep.n_invalid_rows == 3  # row 0 is clean
    assert rep.coerced["age"].tolist()[0] == 30
    mask = rep.error_mask(["age"], {"type"})
    assert mask["age"].tolist() == [False, True, False, False]
    assert rep.to_dict()["n_errors"] == len(rep.errors)


def test_validator_schema_level_errors():
    schema = Schema("s", fields={"a": Field("a", DataType.INTEGER)}, strict=True)
    rep = SchemaValidator(schema).validate(pd.DataFrame({"b": [1]}))
    assert any("missing column" in e for e in rep.schema_errors)
    assert any("unexpected" in e for e in rep.schema_errors)


def test_type_coercer_values():
    c = TypeCoercer()
    assert c.coerce("123", "integer").value == 123
    r = c.coerce("12.5", DataType.INTEGER)
    assert r.success and r.lossy
    assert c.coerce("$1,234.50", "float").value == pytest.approx(1234.5)
    assert c.coerce("(5)", "float").value == -5
    assert c.coerce("yes", "boolean").value is True
    assert c.coerce("1", "boolean").lossy
    assert c.coerce("2024-01-15", "datetime").value == datetime(2024, 1, 15)
    assert not c.coerce("nope", "float").success
    assert c.coerce(None, "integer").value is None


def test_coerce_series_and_frame():
    s, failed = coerce_series(pd.Series(["1", "2", "x", None]), "integer")
    assert failed.tolist() == [False, False, True, False]
    assert s.dtype == "Int64"
    b, failed = coerce_series(pd.Series(["Y", "off", "?"]), "boolean")
    assert b.tolist()[:2] == [True, False] and failed.tolist() == [False, False, True]
    schema = Schema("s", fields={"a": Field("a", DataType.FLOAT)})
    out, mask = coerce_frame(pd.DataFrame({"a": ["1.5", "bad"], "z": [1, 2]}), schema)
    assert out["a"].iloc[0] == 1.5 and mask["a"].tolist() == [False, True]


def test_quality_metrics():
    schema = make_schema()
    df = pd.DataFrame(
        {
            "id": [1, 2, 3, 3],
            "age": [10, 20, None, 40],
            "email": ["a@b.com"] * 4,
            "code": ["AB"] * 4,
            "tier": ["gold"] * 4,
            "active": [True] * 4,
            "joined": ["2026-01-01"] * 4,
        }
    )
    q = compute_quality(df, schema)
    assert q.completeness == pytest.approx(1 - 1 / 28)
    assert q.uniqueness == pytest.approx(0.75)
    assert q.validity == pytest.approx(0.5)  # duplicate id makes both rows invalid (unique)
    assert q.freshness is None
    assert 0 < q.score < 1


def test_quality_freshness():
    df = pd.DataFrame({"ts": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"], "v": [1, 2]})
    now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    assert compute_quality(df, timestamp_column="ts", max_age_hours=24, now=now).freshness == 1.0
    later = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)  # 36h old, max 24h -> 0.5
    assert compute_quality(
        df, timestamp_column="ts", max_age_hours=24, now=later
    ).freshness == pytest.approx(0.5)
    perfect = compute_quality(pd.DataFrame({"a": [1, 2, 3]}))
    assert perfect.score == 1.0
