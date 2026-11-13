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
from anomalyguard.schema.coercion import coerce_series, is_missing, whole_numbers
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

    def __init__(
        self,
        method: str = "median",
        value: Any = None,
        groups: pd.Series | None = None,
        min_group_size: int = 8,
    ):
        if method not in self.CONFIDENCE:
            raise ValueError(f"Unknown imputation method '{method}'")
        self.method = method
        self.value = value
        self.name = f"impute_{method}"
        self.confidence = self.CONFIDENCE[method]
        self.groups = groups  # mean/median are computed per group when given
        self.min_group_size = min_group_size

    def _stat(self, nums: pd.Series, integer: bool) -> float:
        fill = float(nums.mean() if self.method == "mean" else nums.median())
        return round(fill) if integer else fill

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
            integer = pd.api.types.is_integer_dtype(s.dtype) or bool(
                len(nums) and np.all(np.mod(nums, 1) == 0)
            )
            fill = self._stat(nums, integer)
            if self.groups is None:
                _set(df, rows, column, fill)
            else:
                keys = self.groups.astype(str).reset_index(drop=True)
                values = _numeric(s).reset_index(drop=True)
                fills = []
                for r in rows.tolist():
                    same = (keys == keys.iloc[r]).to_numpy() & ~mask
                    g = values[same].dropna()
                    fills.append(self._stat(g, integer) if len(g) >= self.min_group_size else fill)
                _set(df, rows, column, np.asarray(fills, dtype=float))
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


def _decimals(s: pd.Series, limit: int = 6) -> int:
    """Decimal places used by the column's values (e.g. 2 for prices)."""
    nums = _numeric(s).dropna()
    if nums.empty:
        return limit
    sample = nums.iloc[: min(len(nums), 2000)]
    places = 0
    for v in sample:
        text = f"{v:.{limit}f}".rstrip("0")
        places = max(places, len(text.split(".")[1]) if "." in text else 0)
        if places >= limit:
            break
    return places


def never_negative(
    values: pd.Series, mask: np.ndarray | None = None, schema_min: float | None = None
) -> bool:
    """A column that is (almost) never negative: schema ``min >= 0``, no negative
    value among the unflagged cells, or fewer than 1% of all values below zero
    (those few are the anomalies)."""
    if schema_min is not None and schema_min >= 0:
        return True
    present = _numeric(values)
    clean = present[~mask].dropna() if mask is not None else present.dropna()
    present = present.dropna()
    if not len(present) or present.median() <= 0:
        return False
    return bool(len(clean) and clean.min() >= 0) or float((present < 0).mean()) < 0.01


class Cap(Strategy):
    """Clip flagged values to robust fences ``median +- k * MAD / 0.6745``
    computed from the unflagged values (the same fences as the MAD detector;
    on a log scale for positive, right-skewed columns).

    * ``groups`` (one key per row): fences are computed within each group from
      that group's unflagged values, so a value is never pulled into another
      group's range (e.g. yen prices into a dollar range). Groups with fewer
      than ``min_group_size`` unflagged values use the column's fences.
    * Columns that are never negative get a lower fence of at least 0, and
      integer columns get fences rounded outward (floor/ceil), so values on
      the boundary are not nudged.

    Capping is only safe for values that are moderately out of range. A value
    far beyond the fences (by default more than ``max_stretch`` fence widths
    past them, e.g. a price typed x100) or with the wrong sign for a column
    that is never negative is a different kind of error: clipping it would
    write a plausible-looking but wrong number. Such values are left as they
    are (the remediation pipeline sends them to review) and listed in
    :attr:`skipped` with the reason, as are flagged values that already lie
    inside the fences.
    """

    name = "cap"
    confidence = 0.8

    def __init__(
        self,
        k: float = 3.5,
        max_stretch: float = 3.0,
        groups: pd.Series | None = None,
        group_label: str = "group",
        min_group_size: int = 8,
        non_negative: bool | None = None,
    ):
        self.k = k
        self.max_stretch = max_stretch
        self.groups = groups
        self.group_label = group_label
        self.min_group_size = min_group_size
        self.non_negative = non_negative
        self.skipped: dict[int, str] = {}

    def _fences(self, clean: pd.Series) -> tuple[float, float, bool] | None:
        """``(lo, hi, log)``: fences on the working scale (log when ``log``)."""
        from anomalyguard.detect.statistical import prefers_log_scale

        clean = clean.dropna()
        if clean.empty:
            return None
        log = prefers_log_scale(clean.to_numpy(dtype=float))
        x = np.log(clean[clean > 0]) if log else clean
        med = float(x.median())
        mad = float((x - med).abs().median())
        if mad == 0:
            mad = float((x - med).abs().mean()) * 1.2533 * 0.6745
        width = self.k * mad / 0.6745
        return med - width, med + width, log

    def bounds(self, s: pd.Series, mask: np.ndarray) -> tuple[float, float] | None:
        """Column-wide fences on the original scale."""
        f = self._fences(_numeric(s[~mask]))
        if f is None:
            return None
        lo, hi, log = f
        return (float(np.exp(lo)), float(np.exp(hi))) if log else (lo, hi)

    def apply(self, df, column, mask, reason=""):
        self.skipped = {}
        rows = np.flatnonzero(mask)
        if not len(rows):
            return []
        nums = _numeric(df[column])
        all_clean = nums[~mask].dropna()
        column_fences = self._fences(all_clean)
        if column_fences is None:
            return []
        non_negative = (
            self.non_negative if self.non_negative is not None else never_negative(nums, mask)
        )
        integer = pd.api.types.is_integer_dtype(df[column].dtype) or bool(
            len(all_clean) and np.all(np.mod(all_clean, 1) == 0)
        )
        decimals = _decimals(all_clean)
        if self.groups is not None:
            keys = self.groups.astype(str).reset_index(drop=True)
            batches = keys.iloc[rows].groupby(keys.iloc[rows]).groups
            batches = {k: np.asarray(v) for k, v in batches.items()}
        else:
            keys = None
            batches = {None: rows}

        before = df[column].copy()
        new_values: dict[int, float] = {}
        notes: dict[int, str] = {}
        for key, group_rows in batches.items():
            fences, where = column_fences, ""
            if keys is not None:
                in_group = (keys == key).to_numpy()
                g_clean = nums[in_group & ~mask].dropna()
                if len(g_clean) >= self.min_group_size:
                    fences = self._fences(g_clean) or column_fences
                    where = f" for {self.group_label}={key}"
                else:
                    where = f" (column range; {self.group_label}={key} has too few values)"
            lo_s, hi_s, log = fences
            reach = self.max_stretch * max(hi_s - lo_s, 1e-12) / 2
            lo, hi = (float(np.exp(lo_s)), float(np.exp(hi_s))) if log else (lo_s, hi_s)
            if non_negative:
                lo = max(lo, 0.0)
            if integer:
                lo, hi = float(np.floor(lo)), float(np.ceil(hi))
            expected = f"expected {fmt(lo)} to {fmt(hi)}{where}"
            for r in np.asarray(group_rows).tolist():
                v = nums.iloc[r]
                if pd.isna(v):
                    continue
                if non_negative and v < 0:
                    self.skipped[r] = (
                        f"negative value in a column that is never negative; not capped ({expected})"
                    )
                    continue
                v_s = (np.log(v) if v > 0 else -np.inf) if log else v
                if v_s > hi_s + reach or v_s < lo_s - reach:
                    self.skipped[r] = (
                        f"too far outside the expected range ({expected}) to cap safely "
                        "(possible unit or typing error)"
                    )
                elif lo <= v <= hi:
                    self.skipped[r] = f"within the capping range ({expected}); left unchanged"
                else:
                    capped = min(max(v, lo), hi)
                    new_values[r] = round(capped) if integer else round(capped, decimals)
                    notes[r] = f"capped to [{fmt(lo)}, {fmt(hi)}]{where}"
        if not new_values:
            return []
        changed = np.asarray(sorted(new_values), dtype=int)
        _set(df, changed, column, np.asarray([new_values[r] for r in changed.tolist()]))
        out = []
        for r in changed.tolist():
            b, a = before.iloc[r], df[column].iloc[r]
            if not is_missing(b) and not is_missing(a) and b == a:
                continue
            out.append(Change(r, column, b, a, self.name, reason or notes[r], self.confidence))
        return out


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
                and whole_numbers(nn)
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
