"""Data-quality dimensions and an overall quality score."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from anomalyguard.schema.registry import Schema
from anomalyguard.schema.validator import SchemaValidator, ValidationReport

DEFAULT_WEIGHTS = {"completeness": 0.3, "validity": 0.4, "uniqueness": 0.2, "freshness": 0.1}


@dataclass
class QualityMetrics:
    """Quality dimensions, each in ``[0, 1]`` (1 = perfect)."""

    n_rows: int
    n_columns: int
    completeness: float
    validity: float
    uniqueness: float
    freshness: float | None
    score: float
    null_counts: dict[str, int] = field(default_factory=dict)
    duplicate_rows: int = 0
    invalid_rows: int = 0
    violations: dict[str, int] = field(default_factory=dict)
    newest_timestamp: str | None = None
    computed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_quality(
    df: pd.DataFrame,
    schema: Schema | None = None,
    validation: ValidationReport | None = None,
    timestamp_column: str | None = None,
    max_age_hours: float | None = None,
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> QualityMetrics:
    """Compute completeness, validity, uniqueness and freshness.

    * completeness - share of non-missing cells
    * validity     - share of rows with no schema violation (1.0 without a schema)
    * uniqueness   - share of rows that are not duplicates (primary key if defined,
      otherwise the full row)
    * freshness    - 1.0 when the newest timestamp is within ``max_age_hours``, decaying
      linearly to 0 at twice that age; ``None`` when not configured
    """
    weights = weights or DEFAULT_WEIGHTS
    n_rows, n_cols = df.shape
    cols = list(schema.fields) if schema else list(df.columns)
    cols = [c for c in cols if c in df.columns] or list(df.columns)

    nulls = df[cols].isna().sum()
    total_cells = max(n_rows * len(cols), 1)
    completeness = 1.0 - float(nulls.sum()) / total_cells if n_rows else 1.0

    if schema is not None and validation is None:
        validation = SchemaValidator(schema).validate(df)
    if validation is not None and n_rows:
        validity = 1.0 - validation.n_invalid_rows / n_rows
        violations = validation.counts_by_rule()
        invalid_rows = validation.n_invalid_rows
    else:
        validity, violations, invalid_rows = 1.0, {}, 0

    pk = [c for c in ((schema.primary_key if schema else None) or []) if c in df.columns]
    dup_mask = df.duplicated(subset=pk or None, keep="first") if n_rows else pd.Series(dtype=bool)
    duplicate_rows = int(dup_mask.sum())
    uniqueness = 1.0 - duplicate_rows / n_rows if n_rows else 1.0

    ts_col = timestamp_column or (schema.timestamp_column if schema else None)
    max_age = (
        max_age_hours if max_age_hours is not None else (schema.max_age_hours if schema else None)
    )
    freshness: float | None = None
    newest: str | None = None
    if ts_col and ts_col in df.columns and n_rows:
        ts = pd.to_datetime(df[ts_col], errors="coerce", utc=True, format="mixed").dropna()
        if len(ts):
            newest_ts = ts.max()
            newest = newest_ts.isoformat()
            if max_age:
                now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
                if now_ts.tzinfo is None:
                    now_ts = now_ts.tz_localize("UTC")
                age_h = (now_ts - newest_ts).total_seconds() / 3600.0
                if age_h <= max_age:
                    freshness = 1.0
                else:
                    freshness = max(0.0, 1.0 - (age_h - max_age) / max_age)

    parts = {"completeness": completeness, "validity": validity, "uniqueness": uniqueness}
    if freshness is not None:
        parts["freshness"] = freshness
    wsum = sum(weights.get(k, 0.0) for k in parts)
    score = sum(parts[k] * weights.get(k, 0.0) for k in parts) / wsum if wsum else 0.0

    return QualityMetrics(
        n_rows=n_rows,
        n_columns=n_cols,
        completeness=round(completeness, 6),
        validity=round(validity, 6),
        uniqueness=round(uniqueness, 6),
        freshness=None if freshness is None else round(freshness, 6),
        score=round(score, 6),
        null_counts={c: int(v) for c, v in nulls.items() if v},
        duplicate_rows=duplicate_rows,
        invalid_rows=invalid_rows,
        violations=violations,
        newest_timestamp=newest,
    )
