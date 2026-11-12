"""Type coercion for single values and whole columns.

Coercion never raises: values that cannot be converted become missing and are
reported through a ``failed`` mask so the validator can turn them into
type errors and the remediation layer can impute them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.schema.registry import DataType, Schema

TRUE_VALUES = {"true", "t", "yes", "y", "1", "on"}
FALSE_VALUES = {"false", "f", "no", "n", "0", "off"}
_NUMERIC_JUNK = re.compile(r"[,\s$€£%]")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    try:
        return bool(pd.isna(value)) if np.isscalar(value) else False
    except (TypeError, ValueError):
        return False


@dataclass
class CoercionResult:
    value: Any
    success: bool
    lossy: bool = False
    error: str | None = None


class TypeCoercer:
    """Convert values to a target :class:`DataType`."""

    def coerce(self, value: Any, target: DataType | str) -> CoercionResult:
        target = DataType(target)
        if is_missing(value):
            return CoercionResult(None, True)
        try:
            if target == DataType.INTEGER:
                num = _to_number(value)
                as_int = round(num)
                return CoercionResult(as_int, True, lossy=not float(num).is_integer())
            if target == DataType.FLOAT:
                return CoercionResult(float(_to_number(value)), True)
            if target == DataType.BOOLEAN:
                if isinstance(value, (bool, np.bool_)):
                    return CoercionResult(bool(value), True)
                s = str(value).strip().lower()
                if s in TRUE_VALUES:
                    return CoercionResult(True, True, lossy=s in {"1", "on"})
                if s in FALSE_VALUES:
                    return CoercionResult(False, True, lossy=s in {"0", "off"})
                raise ValueError(f"not a boolean: {value!r}")
            if target == DataType.DATETIME:
                ts = pd.Timestamp(value)
                if ts is pd.NaT:
                    raise ValueError(f"not a datetime: {value!r}")
                return CoercionResult(ts.to_pydatetime(), True)
            if target in (DataType.STRING, DataType.CATEGORICAL):
                return CoercionResult(str(value), True)
            return CoercionResult(value, True)
        except (ValueError, TypeError, OverflowError) as exc:
            return CoercionResult(value, False, error=str(exc))


def _to_number(value: Any) -> float:
    if isinstance(value, (bool, np.bool_)):
        return float(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    s = _NUMERIC_JUNK.sub("", str(value))
    if s.startswith("(") and s.endswith(")"):  # accounting negative
        s = "-" + s[1:-1]
    return float(s)


def _clean_numeric_strings(series: pd.Series) -> pd.Series:
    if series.dtype != object and not pd.api.types.is_string_dtype(series):
        return series
    return series.map(lambda v: _NUMERIC_JUNK.sub("", v) if isinstance(v, str) else v)


def coerce_series(series: pd.Series, target: DataType | str) -> tuple[pd.Series, pd.Series]:
    """Coerce a column. Returns ``(coerced, failed)`` where ``failed`` marks
    values that were present but could not be converted."""
    target = DataType(target)
    present = series.notna()
    if target in (DataType.INTEGER, DataType.FLOAT):
        if pd.api.types.is_bool_dtype(series):
            out = series.astype(float)
        else:
            out = pd.to_numeric(_clean_numeric_strings(series), errors="coerce")
        out = out.astype(float)
        if target == DataType.INTEGER:
            non_null = out.dropna()
            if len(non_null) and np.all(np.mod(non_null, 1) == 0):
                out = out.astype("Int64")
    elif target == DataType.BOOLEAN:

        def _b(v: Any) -> Any:
            if is_missing(v):
                return pd.NA
            if isinstance(v, (bool, np.bool_)):
                return bool(v)
            s = str(v).strip().lower()
            if s in TRUE_VALUES:
                return True
            if s in FALSE_VALUES:
                return False
            return pd.NA

        out = series.map(_b).astype("boolean")
    elif target == DataType.DATETIME:
        if pd.api.types.is_datetime64_any_dtype(series):
            out = series
        else:
            out = pd.to_datetime(series, errors="coerce", format="mixed")
    elif target in (DataType.STRING, DataType.CATEGORICAL):
        out = series.map(lambda v: v if is_missing(v) else str(v)).astype(object)
    else:
        out = series
    failed = present & out.isna()
    return out, failed


def coerce_frame(df: pd.DataFrame, schema: Schema) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coerce every schema column. Returns ``(coerced_df, failed_mask_df)``."""
    out = df.copy()
    failed = pd.DataFrame(False, index=df.index, columns=df.columns)
    for name, fld in schema.fields.items():
        if name not in out.columns:
            continue
        out[name], failed[name] = coerce_series(df[name], fld.dtype)
    return out, failed
