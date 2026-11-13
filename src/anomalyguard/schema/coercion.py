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
# Whole numbers beyond 2**53 are not exactly representable as floats, so a
# column of such values is treated as float rather than integer.
MAX_SAFE_INTEGER = 2**53


def whole_numbers(values: Any) -> bool:
    """True when every value is a finite whole number that fits an integer type safely."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return True
    if not np.all(np.isfinite(arr)):
        return False
    return bool(np.all(np.mod(arr, 1) == 0) and np.max(np.abs(arr)) < MAX_SAFE_INTEGER)


def _nan_tokens(series: pd.Series) -> pd.Series:
    """Text cells spelling NaN (e.g. written by another tool): missing, not invalid."""
    if series.dtype != object and not pd.api.types.is_string_dtype(series):
        return pd.Series(False, index=series.index)
    return series.map(lambda v: isinstance(v, str) and v.strip().lower() == "nan").astype(bool)


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
                if not math.isfinite(num):
                    raise ValueError(f"not a finite number: {value!r}")
                as_int = round(num)
                return CoercionResult(as_int, True, lossy=not float(num).is_integer())
            if target == DataType.FLOAT:
                num = float(_to_number(value))
                if not math.isfinite(num):
                    raise ValueError(f"not a finite number: {value!r}")
                return CoercionResult(num, True)
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


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
_reported_date_orders: set[tuple[str, bool]] = set()


def day_first_order(series: pd.Series) -> tuple[bool | None, int, int]:
    """Decide the day/month order of numeric dates such as ``03/04/2026``.

    Returns ``(day_first, n_day_first, n_month_first)`` where the counts are
    values that only fit one order (``13/01/2026`` must be day-first,
    ``01/13/2026`` month-first). ``day_first`` is None when both kinds occur.
    """
    text = series[series.map(lambda v: isinstance(v, str))]
    parts = text.str.extract(_NUMERIC_DATE)
    parts = parts[parts[0].notna()]
    if parts.empty:
        return False, 0, 0
    a, b = parts[0].astype(int), parts[1].astype(int)
    n_day = int(((a > 12) & (b <= 12)).sum())
    n_month = int(((b > 12) & (a <= 12)).sum())
    if n_day and n_month:
        return None, n_day, n_month
    return bool(n_day), n_day, n_month


def parse_dates(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse mixed date strings. Returns ``(timestamps, ambiguous)``.

    Numeric dates (``11/01/2026``) are read in the one day/month order that the
    column's unambiguous values allow (any ``13/01/2026`` means day-first). If
    the column contains both orders, values that fit either (both parts <= 12
    and different) are ambiguous: they are not guessed and come back missing,
    marked in ``ambiguous``.
    """
    import logging

    is_text = series.map(lambda v: isinstance(v, str)).to_numpy(dtype=bool)
    flags = np.zeros(len(series), dtype=bool)
    if is_text.any():
        flags[is_text] = series[is_text].str.match(_NUMERIC_DATE).to_numpy(dtype=bool)
    numeric = pd.Series(flags, index=series.index)
    ambiguous = pd.Series(False, index=series.index)
    if not numeric.any():
        return pd.to_datetime(series, errors="coerce", format="mixed"), ambiguous
    day_first, n_day, n_month = day_first_order(series)
    parts = series[numeric].str.extract(_NUMERIC_DATE)
    a, b = parts[0].astype(int), parts[1].astype(int)
    unclear = (a <= 12) & (b <= 12) & (a != b)
    out = pd.to_datetime(series.where(~numeric), errors="coerce", format="mixed")
    name = str(series.name)
    if day_first is None:
        ambiguous[numeric] = unclear.to_numpy()
        keep = numeric & ~ambiguous
        sure = series[keep]
        sure_parts = parts[~unclear.to_numpy()]
        firsts = (sure_parts[0].astype(int) > 12).to_numpy()
        out[keep] = [
            pd.to_datetime(v, errors="coerce", dayfirst=bool(df_))
            for v, df_ in zip(sure, firsts, strict=True)
        ]
        key = (name, None)
    else:
        out[numeric] = pd.to_datetime(
            series[numeric], errors="coerce", format="mixed", dayfirst=day_first
        )
        key = (name, day_first)
    if unclear.any() and key not in _reported_date_orders:
        _reported_date_orders.add(key)  # type: ignore[arg-type]
        log = logging.getLogger("anomalyguard.schema")
        if day_first is None:
            log.warning(
                "%s: dates use both day/month and month/day order (%d and %d values); "
                "%d ambiguous dates such as %s are treated as invalid",
                name,
                n_day,
                n_month,
                int(unclear.sum()),
                series[numeric][unclear.to_numpy()].iloc[0],
            )
        else:
            order = "day/month/year" if day_first else "month/day/year"
            evidence = n_day if day_first else n_month
            log.warning(
                "%s: dates such as %s read as %s%s",
                name,
                series[numeric][unclear.to_numpy()].iloc[0],
                order,
                f" ({evidence} values only fit that order)"
                if evidence
                else " (no value decides the order; month first assumed)",
            )
    return pd.to_datetime(out, errors="coerce"), ambiguous


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
        # +-inf is not a usable measurement: report it as invalid
        out = out.where(~np.isinf(out), np.nan)
        present = present & ~_nan_tokens(series)
        if target == DataType.INTEGER:
            non_null = out.dropna()
            if len(non_null) and whole_numbers(non_null):
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
            out, _ambiguous = parse_dates(series)  # ambiguous dates come back missing -> failed
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
