"""Cell-level remediation strategies.

Each strategy modifies a DataFrame in place for the cells selected by a
boolean ``mask`` (positional) and returns a list of :class:`Change` records.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.detect.base import fmt
from anomalyguard.schema.coercion import coerce_series, is_missing
from anomalyguard.schema.registry import DataType


@dataclass
class Change:
    row: int  # positional row in the input
    column: str | None
    before: Any
    after: Any
    strategy: str
    reason: str = ""
    confidence: float = 1.0
    index: Any = None

    def to_dict(self) -> dict[str, Any]:
        def clean(v: Any) -> Any:
            if is_missing(v):
                return None
            if isinstance(v, (np.integer,)):
                return int(v)
            if isinstance(v, (np.floating,)):
                return float(v)
            if isinstance(v, (np.bool_,)):
                return bool(v)
            if isinstance(v, pd.Timestamp):
                return v.isoformat()
            return v

        idx = self.index.item() if hasattr(self.index, "item") else self.index
        return {
            "row": int(self.row),
            "index": idx if isinstance(idx, (int, float, str, type(None))) else str(idx),
            "column": self.column,
            "before": clean(self.before),
            "after": clean(self.after),
            "strategy": self.strategy,
            "reason": self.reason,
            "confidence": round(float(self.confidence), 3),
        }


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype(float)


def _set(df: pd.DataFrame, rows: np.ndarray, column: str, values: Any) -> None:
    col = df.columns.get_loc(column)
    if pd.api.types.is_integer_dtype(
        df[column].dtype
    ) and not pd.api.types.is_extension_array_dtype(df[column].dtype):
        vals = np.asarray(values, dtype=float) if np.ndim(values) else values
        if np.any(~np.isfinite(np.atleast_1d(vals))) or np.any(np.mod(np.atleast_1d(vals), 1) != 0):
            df[column] = df[column].astype(float)
    df.iloc[rows, col] = values


class Strategy(ABC):
    name = "strategy"
    confidence = 0.5

    @abstractmethod
    def apply(
        self, df: pd.DataFrame, column: str, mask: np.ndarray, reason: str = ""
    ) -> list[Change]: ...

    def _changes(
        self, df_before: pd.Series, df: pd.DataFrame, column: str, rows: np.ndarray, reason: str
    ) -> list[Change]:
        out = []
        after = df[column]
        for r in rows.tolist():
            b, a = df_before.iloc[r], after.iloc[r]
            if (is_missing(b) and is_missing(a)) or (
                not is_missing(b) and not is_missing(a) and b == a
            ):
                continue
            out.append(Change(r, column, b, a, self.name, reason, self.confidence))
        return out


class Impute(Strategy):
    """Fill missing cells: ``mean``, ``median``, ``mode``, ``ffill``, ``bfill``,
    ``interpolate`` (linear, numeric) or ``constant``. Statistics are computed
    from cells that are present and not masked."""

    CONFIDENCE = {
        "mean": 0.6,
        "median": 0.7,
        "mode": 0.6,
        "ffill": 0.7,
        "bfill": 0.7,
        "interpolate": 0.8,
        "constant": 0.9,
    }

    def __init__(self, method: str = "median", value: Any = None):
        if method not in self.CONFIDENCE:
            raise ValueError(f"Unknown imputation method '{method}'")
        self.method = method
        self.value = value
        self.name = f"impute_{method}"
        self.confidence = self.CONFIDENCE[method]

    def apply(self, df, column, mask, reason=""):
        rows = np.flatnonzero(mask)
        if len(rows) == 0:
            return []
        before = df[column].copy()
        s = df[column]
        clean = s[~mask & s.notna().to_numpy()]
        if self.method in ("mean", "median"):
            nums = _numeric(clean).dropna()
            if nums.empty:
                return []
            fill = float(nums.mean() if self.method == "mean" else nums.median())
            if pd.api.types.is_integer_dtype(s.dtype) or (
                len(nums) and np.all(np.mod(nums, 1) == 0)
            ):
                fill = round(fill)
            _set(df, rows, column, fill)
        elif self.method == "mode":
            if clean.empty:
                return []
            _set(df, rows, column, clean.mode(dropna=True).iloc[0])
        elif self.method == "constant":
            _set(df, rows, column, self.value)
        else:
            tmp = s.copy()
            tmp.iloc[rows] = np.nan
            if self.method == "ffill":
                filled = tmp.ffill().bfill()
            elif self.method == "bfill":
                filled = tmp.bfill().ffill()
            else:
                filled = _numeric(tmp).interpolate(limit_direction="both")
                if np.all(np.mod(_numeric(clean).dropna(), 1) == 0):
                    filled = filled.round()
            _set(df, rows, column, filled.iloc[rows].to_numpy())
        return self._changes(before, df, column, rows, reason or "missing value")


class Cap(Strategy):
    """Clip flagged values to robust fences ``median +- k * MAD / 0.6745``
    computed from the unflagged values (the same fences as the MAD detector)."""

    name = "cap"
    confidence = 0.8

    def __init__(self, k: float = 3.5):
        self.k = k

    def bounds(self, s: pd.Series, mask: np.ndarray) -> tuple[float, float] | None:
        clean = _numeric(s[~mask]).dropna()
        if clean.empty:
            return None
        med = float(clean.median())
        mad = float((clean - med).abs().median())
        if mad == 0:
            mad = float((clean - med).abs().mean()) * 1.2533 * 0.6745
        width = self.k * mad / 0.6745
        return med - width, med + width

    def apply(self, df, column, mask, reason=""):
        rows = np.flatnonzero(mask)
        b = self.bounds(df[column], mask)
        if not len(rows) or b is None:
            return []
        before = df[column].copy()
        vals = _numeric(df[column]).iloc[rows].clip(b[0], b[1])
        if pd.api.types.is_integer_dtype(df[column].dtype) or np.all(
            np.mod(_numeric(df[column]).dropna(), 1) == 0
        ):
            vals = vals.round()
        _set(df, rows, column, vals.to_numpy())
        return self._changes(
            before, df, column, rows, reason or f"capped to [{fmt(b[0])}, {fmt(b[1])}]"
        )


class Winsorize(Strategy):
    """Clip flagged values to the ``lower``/``upper`` quantiles of the column."""

    name = "winsorize"
    confidence = 0.7

    def __init__(self, lower: float = 0.01, upper: float = 0.99):
        self.lower, self.upper = lower, upper

    def apply(self, df, column, mask, reason=""):
        rows = np.flatnonzero(mask)
        nums = _numeric(df[column])
        if not len(rows) or nums.dropna().empty:
            return []
        lo, hi = nums.quantile(self.lower), nums.quantile(self.upper)
        before = df[column].copy()
        _set(df, rows, column, nums.iloc[rows].clip(lo, hi).to_numpy())
        return self._changes(
            before, df, column, rows, reason or f"winsorized to [{fmt(lo)}, {fmt(hi)}]"
        )


class Clip(Strategy):
    """Clip to an explicit ``[min, max]`` range (e.g. from schema constraints)."""

    name = "clip"
    confidence = 0.9

    def __init__(self, min: float | None = None, max: float | None = None):
        self.min, self.max = min, max

    def apply(self, df, column, mask, reason=""):
        rows = np.flatnonzero(mask)
        if not len(rows) or (self.min is None and self.max is None):
            return []
        before = df[column].copy()
        vals = _numeric(df[column]).iloc[rows].clip(self.min, self.max)
        _set(df, rows, column, vals.to_numpy())
        return self._changes(
            before, df, column, rows, reason or f"clipped to [{fmt(self.min)}, {fmt(self.max)}]"
        )


class SetNull(Strategy):
    """Replace flagged values with missing (typically followed by imputation)."""

    name = "set_null"
    confidence = 1.0

    def apply(self, df, column, mask, reason=""):
        rows = np.flatnonzero(mask)
        if not len(rows):
            return []
        before = df[column].copy()
        if pd.api.types.is_integer_dtype(
            df[column].dtype
        ) and not pd.api.types.is_extension_array_dtype(df[column].dtype):
            df[column] = df[column].astype(float)
        df.iloc[rows, df.columns.get_loc(column)] = np.nan
        return self._changes(before, df, column, rows, reason)


class TypeFix(Strategy):
    """Coerce a column to ``dtype``; unparseable values become missing."""

    name = "type_fix"
    confidence = 1.0

    def __init__(self, dtype: DataType | str):
        self.dtype = DataType(dtype)

    def apply(self, df, column, mask=None, reason=""):
        before = df[column].copy()
        coerced, failed = coerce_series(df[column], self.dtype)
        if self.dtype.is_numeric:
            coerced = coerced.astype(float)
            nn = coerced.dropna()
            if (
                self.dtype == DataType.INTEGER
                and len(nn)
                and np.all(np.mod(nn, 1) == 0)
                and not coerced.isna().any()
            ):
                coerced = coerced.astype("int64")
        df[column] = coerced
        rows = np.flatnonzero(failed.to_numpy())
        return [
            Change(
                int(r),
                column,
                before.iloc[r],
                None,
                self.name,
                reason or f"cannot parse {before.iloc[r]!r} as {self.dtype.value}",
                1.0,
            )
            for r in rows
        ]


def normalise_categories(df: pd.DataFrame, column: str, allowed: list[Any]) -> list[Change]:
    """Map values that match an allowed value after trimming/case-folding."""
    lookup = {str(a).strip().lower(): a for a in allowed}
    allowed_set = set(allowed)
    changes = []
    s = df[column]
    for r in range(len(s)):
        v = s.iloc[r]
        if is_missing(v) or v in allowed_set:
            continue
        key = str(v).strip().lower()
        if key in lookup:
            df.iloc[r, df.columns.get_loc(column)] = lookup[key]
            changes.append(
                Change(r, column, v, lookup[key], "normalise_category", "case/whitespace fix", 0.95)
            )
    return changes
