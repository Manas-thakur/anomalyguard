"""Schema inference and column profiling from a sample of data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.schema.coercion import (
    FALSE_VALUES,
    TRUE_VALUES,
    _clean_numeric_strings,
    _nan_tokens,
    whole_numbers,
)
from anomalyguard.schema.registry import DataType, Field, Schema

NUMERIC_RATIO = 0.9  # share of present values that must parse for a numeric column
DATETIME_RATIO = 0.9
CATEGORICAL_MAX_UNIQUE = 50
CATEGORICAL_MAX_RATIO = 0.5


# A deliberately simple address shape: something@domain.tld, no spaces.
EMAIL_PATTERN = r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}"


def infer_dtype(series: pd.Series) -> DataType:
    """Infer the logical type of a column, tolerating a few malformed values."""
    s = series.dropna()
    s = s[~_nan_tokens(s)]
    if s.empty:
        return DataType.UNKNOWN
    if pd.api.types.is_bool_dtype(series):
        return DataType.BOOLEAN
    if pd.api.types.is_datetime64_any_dtype(series):
        return DataType.DATETIME
    if pd.api.types.is_numeric_dtype(series):
        finite = s.astype(float)
        finite = finite[np.isfinite(finite)]
        return DataType.INTEGER if whole_numbers(finite) else DataType.FLOAT

    as_str = s.astype(str).str.strip()
    lowered = as_str.str.lower()
    if lowered.isin(TRUE_VALUES | FALSE_VALUES).all() and not lowered.isin({"0", "1"}).all():
        return DataType.BOOLEAN

    nums = pd.to_numeric(_clean_numeric_strings(as_str), errors="coerce")
    if nums.notna().mean() >= NUMERIC_RATIO:
        ok = nums.dropna()
        ok = ok[np.isfinite(ok)]
        return DataType.INTEGER if whole_numbers(ok) else DataType.FLOAT

    looks_temporal = as_str.str.contains(r"\d[-/:T]\d", regex=True).mean() >= DATETIME_RATIO
    if looks_temporal:
        dts = pd.to_datetime(as_str, errors="coerce", format="mixed")
        if dts.notna().mean() >= DATETIME_RATIO:
            return DataType.DATETIME

    n_unique = as_str.nunique()
    if n_unique <= CATEGORICAL_MAX_UNIQUE and n_unique / len(as_str) <= CATEGORICAL_MAX_RATIO:
        return DataType.CATEGORICAL
    return DataType.STRING


def infer_schema(
    df: pd.DataFrame,
    name: str = "inferred",
    sample_size: int | None = 10_000,
    infer_constraints: bool = True,
) -> Schema:
    """Infer a :class:`Schema` from data.

    With ``infer_constraints`` the engine also adds conservative constraints:
    ``nullable: false`` for columns without nulls, ``min: 0`` for non-negative
    numeric columns, ``allowed`` values for small categoricals, and ``unique``
    for id-like columns (which also become the primary key).
    """
    sample = (
        df
        if sample_size is None or len(df) <= sample_size
        else df.sample(sample_size, random_state=0)
    )
    schema = Schema(name=name)
    for col in df.columns:
        s = sample[col]
        dtype = infer_dtype(s)
        fld = Field(
            name=str(col), dtype=dtype, nullable=bool(s.isna().any()) or not infer_constraints
        )
        if infer_constraints and len(s.dropna()):
            present = s.dropna()
            if dtype.is_numeric:
                nums = pd.to_numeric(_clean_numeric_strings(present), errors="coerce").dropna()
                nums = nums[np.isfinite(nums.astype(float))]
                if len(nums) and nums.min() >= 0:
                    fld.min = 0
            elif dtype == DataType.CATEGORICAL and present.nunique() <= 20:
                fld.allowed = sorted(present.astype(str).unique().tolist())
            elif dtype == DataType.DATETIME:
                # Historical data (at least 95% of it in the past) should stay
                # there: "now" is evaluated at validation time, so the saved
                # schema does not go stale.
                ts = pd.to_datetime(present, errors="coerce", utc=True).dropna()
                if len(ts) >= 10:
                    future = (ts > pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).mean()
                    if future <= 0.05:
                        fld.max = "now"
            elif dtype == DataType.STRING:
                texts = present.astype(str).str.strip()
                looks_email = texts.str.fullmatch(EMAIL_PATTERN).mean() if len(texts) else 0
                # Mostly emails, or a column named like one that mostly holds them.
                named_email = "email" in str(col).lower() and looks_email >= 0.6
                if len(texts) >= 10 and (looks_email >= 0.9 or named_email):
                    fld.pattern = EMAIL_PATTERN
            lname = str(col).lower()
            is_id_name = lname == "id" or lname.endswith("_id")
            mostly_unique = present.nunique() / len(present) >= 0.95
            if is_id_name and mostly_unique and dtype in (DataType.INTEGER, DataType.STRING):
                fld.unique = True
        schema.fields[str(col)] = fld

    uniques = [n for n, f in schema.fields.items() if f.unique]
    if uniques:
        schema.primary_key = [uniques[0]]
    dts = [n for n, f in schema.fields.items() if f.dtype == DataType.DATETIME]
    if dts:
        schema.timestamp_column = dts[0]
    return schema


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    count: int
    nulls: int
    null_pct: float
    unique: int
    mean: float | None = None
    std: float | None = None
    min: Any = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    max: Any = None
    invalid: int = 0
    top_values: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def profile_column(series: pd.Series, dtype: DataType | None = None) -> ColumnProfile:
    dtype = dtype or infer_dtype(series)
    n = len(series)
    nulls = int(series.isna().sum())
    prof = ColumnProfile(
        name=str(series.name),
        dtype=dtype.value,
        count=n - nulls,
        nulls=nulls,
        null_pct=round(100.0 * nulls / n, 2) if n else 0.0,
        unique=int(series.nunique(dropna=True)),
    )
    if dtype.is_numeric:
        nums = pd.to_numeric(_clean_numeric_strings(series), errors="coerce")
        prof.invalid = int((series.notna() & nums.isna()).sum())
        x = nums.dropna().astype(float)
        prof.invalid += int(np.isinf(x).sum())
        x = x[np.isfinite(x)]
        if len(x):
            q = np.percentile(x, [25, 50, 75])
            with np.errstate(over="ignore", invalid="ignore"):
                prof.mean, prof.std = float(x.mean()), float(x.std(ddof=0))
            prof.min, prof.max = float(x.min()), float(x.max())
            prof.p25, prof.median, prof.p75 = (float(v) for v in q)
    elif dtype == DataType.DATETIME:
        ts = pd.to_datetime(series, errors="coerce", format="mixed")
        prof.invalid = int((series.notna() & ts.isna()).sum())
        if ts.notna().any():
            prof.min, prof.max = str(ts.min()), str(ts.max())
    if dtype in (DataType.CATEGORICAL, DataType.STRING, DataType.BOOLEAN):
        vc = series.dropna().astype(str).value_counts().head(5)
        prof.top_values = [(str(k), int(v)) for k, v in vc.items()]
    return prof


def profile(df: pd.DataFrame, schema: Schema | None = None) -> list[ColumnProfile]:
    """Profile every column of ``df`` (types from ``schema`` when given)."""
    out = []
    for col in df.columns:
        dtype = schema.fields[col].dtype if schema and col in schema.fields else None
        out.append(profile_column(df[col], dtype))
    return out
