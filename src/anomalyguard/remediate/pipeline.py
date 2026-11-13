"""Policy-driven remediation: dedupe -> type fixes -> outliers -> constraint
violations -> missing values -> flag/drop what cannot be fixed safely."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.detect.base import _is_id_like
from anomalyguard.detect.contextual import group_keys
from anomalyguard.detect.report import AnomalyReport
from anomalyguard.ingest.inference import infer_dtype
from anomalyguard.remediate.strategies import (
    Cap,
    Change,
    Clip,
    Impute,
    SetNull,
    Strategy,
    TypeFix,
    Winsorize,
    normalise_categories,
)
from anomalyguard.schema.coercion import coerce_series, is_missing, whole_numbers
from anomalyguard.schema.registry import DataType, Schema

MISSING_ACTIONS = {
    "auto",
    "mean",
    "median",
    "mode",
    "ffill",
    "bfill",
    "interpolate",
    "constant",
    "drop",
    "flag",
    "keep",
}
OUTLIER_ACTIONS = {"cap", "winsorize", "clip", "median", "mean", "null", "flag", "drop", "keep"}
INVALID_ACTIONS = {"coerce", "drop", "flag", "keep"}


@dataclass
class ColumnPolicy:
    """What to do with a column's problems.

    * ``missing``: auto | mean | median | mode | ffill | bfill | interpolate | constant | drop | flag | keep
      (``auto`` = median for numbers, mode for categoricals, flag for ids/free text)
    * ``outlier``: cap | winsorize | clip | median | mean | null | flag | drop | keep
    * ``invalid`` (type errors): coerce (-> missing -> imputed) | drop | flag | keep
    """

    missing: str = "auto"
    outlier: str = "cap"
    invalid: str = "coerce"
    constant: Any = None
    min: float | None = None
    max: float | None = None
    cap_k: float = 3.5

    def __post_init__(self) -> None:
        if self.missing not in MISSING_ACTIONS:
            raise ValueError(f"missing policy must be one of {sorted(MISSING_ACTIONS)}")
        if self.outlier not in OUTLIER_ACTIONS:
            raise ValueError(f"outlier policy must be one of {sorted(OUTLIER_ACTIONS)}")
        if self.invalid not in INVALID_ACTIONS:
            raise ValueError(f"invalid policy must be one of {sorted(INVALID_ACTIONS)}")
        if self.outlier == "clip" and self.min is None and self.max is None:
            raise ValueError("outlier: clip needs a range: set min and/or max (CLI: --min/--max)")
        if self.missing == "constant" and self.constant is None:
            raise ValueError(
                "missing: constant needs a fill value: set constant (CLI: --missing-value)"
            )

    @classmethod
    def from_dict(
        cls, data: dict[str, Any] | None, base: ColumnPolicy | None = None
    ) -> ColumnPolicy:
        merged = dict((base or cls()).__dict__)
        merged.update(data or {})
        return cls(**merged)


@dataclass
class RemediationPolicy:
    default: ColumnPolicy = field(default_factory=ColumnPolicy)
    columns: dict[str, ColumnPolicy] = field(default_factory=dict)
    dedupe: bool | list[str] = True
    unattributed: str = "flag"  # rows flagged by multivariate detectors: flag | drop | keep
    flag_column: str | None = None
    fix_types: bool = True

    def for_column(self, column: str) -> ColumnPolicy:
        return self.columns.get(column, self.default)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RemediationPolicy:
        data = dict(data or {})
        default = ColumnPolicy.from_dict(data.pop("default", None))
        columns = {
            c: ColumnPolicy.from_dict(p, default)
            for c, p in (data.pop("columns", None) or {}).items()
        }
        allowed = {"dedupe", "unattributed", "flag_column", "fix_types"}
        extra = set(data) - allowed
        if extra:
            raise ValueError(f"Unknown remediation keys: {sorted(extra)}")
        return cls(default=default, columns=columns, **data)


@dataclass
class FlaggedItem:
    row: int
    index: Any
    column: str | None
    value: Any
    reason: str
    suggestion: Any = None
    suggestion_confidence: float | None = None
    suggestion_rationale: str | None = None
    detector: str | None = None  # detector name, or the problem kind (missing, type, schema)
    applied: bool = False  # the suggestion was written to the output (LLM auto_apply)

    def to_dict(self) -> dict[str, Any]:
        v = self.value
        if is_missing(v):
            v = None
        elif hasattr(v, "item"):
            v = v.item()
        idx = self.index.item() if hasattr(self.index, "item") else self.index
        return {
            "row": int(self.row),
            "index": idx if isinstance(idx, (int, float, str, type(None))) else str(idx),
            "column": self.column,
            "value": v if isinstance(v, (int, float, str, bool, type(None))) else str(v),
            "reason": self.reason,
            "suggestion": self.suggestion,
            "suggestion_confidence": self.suggestion_confidence,
            "suggestion_rationale": self.suggestion_rationale,
            "detector": self.detector,
            "applied": self.applied,
        }


@dataclass
class RemediationResult:
    data: pd.DataFrame
    original: pd.DataFrame
    changes: list[Change]
    dropped: dict[int, str]
    flagged: list[FlaggedItem]

    @property
    def n_changed_cells(self) -> int:
        return sum(1 for c in self.changes if c.column is not None)

    def report(self):
        from anomalyguard.remediate.report import RemediationReport

        return RemediationReport(self)


class RemediationPipeline:
    """Apply a :class:`RemediationPolicy` to a DataFrame.

    ``report`` (from :func:`run_detectors`) tells the pipeline which cells are
    outliers; ``schema`` drives type fixes, required columns and range clipping.
    An optional ``llm`` suggester proposes values for flagged cells.
    """

    def __init__(
        self,
        policy: RemediationPolicy | dict[str, Any] | None = None,
        schema: Schema | None = None,
        llm: Any = None,
        llm_auto_apply: bool = False,
        llm_min_confidence: float = 0.8,
        llm_max_items: int = 20,
    ):
        self.policy = (
            policy if isinstance(policy, RemediationPolicy) else RemediationPolicy.from_dict(policy)
        )
        self.schema = schema
        self.llm = llm
        self.llm_auto_apply = llm_auto_apply
        self.llm_min_confidence = llm_min_confidence
        self.llm_max_items = llm_max_items

    # ------------------------------------------------------------------
    def _dtype(self, df: pd.DataFrame, column: str) -> DataType:
        if self.schema and column in self.schema.fields:
            return self.schema.fields[column].dtype
        return infer_dtype(df[column])

    def run(self, df: pd.DataFrame, report: AnomalyReport | None = None) -> RemediationResult:
        original = df
        index = list(df.index)
        work = df.copy().reset_index(drop=True)
        n = len(work)
        changes: list[Change] = []
        dropped: dict[int, str] = {}
        flagged: list[FlaggedItem] = []
        # cells sent to review keep their value: later steps must not rewrite them,
        # so the review item and the output agree
        self._protected: set[tuple[int, str]] = set()

        def flag(row: int, column: str | None, reason: str, detector: str | None = None) -> None:
            value = work.iloc[row][column] if column else None
            flagged.append(FlaggedItem(row, index[row], column, value, reason, detector=detector))
            if column is not None:
                self._protected.add((row, column))

        # 1. duplicates
        if self.policy.dedupe:
            subset = self.policy.dedupe if isinstance(self.policy.dedupe, list) else None
            if subset is None and self.schema and self.schema.primary_key:
                subset = [c for c in self.schema.primary_key if c in work.columns] or None
            dups = np.flatnonzero(work.duplicated(subset=subset, keep="first").to_numpy())
            for r in dups.tolist():
                dropped[r] = f"duplicate of an earlier row (on {subset or 'all columns'})"

        dtypes = {c: self._dtype(work, c) for c in work.columns}

        # 2. type fixes
        if self.policy.fix_types:
            for col, dt in dtypes.items():
                if not (dt.is_numeric or dt in (DataType.BOOLEAN, DataType.DATETIME)):
                    continue
                pol = self.policy.for_column(col)
                if pol.invalid == "keep":
                    continue
                before = work[col].copy()
                fixes = TypeFix(dt).apply(work, col)
                if pol.invalid in ("drop", "flag"):
                    work[col] = before  # keep original values, act on rows instead
                    for ch in fixes:
                        if pol.invalid == "drop":
                            dropped.setdefault(ch.row, f"type error in {col}: {ch.reason}")
                        else:
                            flag(ch.row, col, f"type error: {ch.reason}", "type")
                else:
                    changes.extend(fixes)

        # 3. outliers (cells attributed by detectors)
        if report is not None and report.n_rows == n:
            cols = [c for c in work.columns if c in set(report.counts_by_column())]
            mask_df = report.column_mask(cols)
            reasons: dict[tuple[int, str], str] = {}
            sources: dict[tuple[int, str], str] = {}
            for f in report.findings:
                if f.column:
                    reasons.setdefault((f.row, f.column), f.reason)
                    sources.setdefault((f.row, f.column), f.detector)
            for col in cols:
                mask = mask_df[col].to_numpy() & work[col].notna().to_numpy()
                if not mask.any():
                    continue
                group_cols = report.group_columns(col)
                groups = None
                if group_cols and all(g in work.columns for g in group_cols):
                    groups = group_keys(work, group_cols)
                changes.extend(
                    self._fix_outliers(
                        work,
                        col,
                        mask,
                        reasons,
                        flag,
                        dropped,
                        sources,
                        dtype=dtypes[col],
                        groups=groups,
                        group_label="/".join(group_cols or []),
                    )
                )
            for r in report.rows_without_column():
                row_findings = [f for f in report.findings if f.row == r]
                reason = "; ".join(f.reason for f in row_findings)
                if self.policy.unattributed == "drop":
                    dropped.setdefault(r, f"anomalous row: {reason}")
                elif self.policy.unattributed == "flag":
                    dets = ",".join(sorted({f.detector for f in row_findings})) or None
                    flag(r, None, f"anomalous row: {reason}", dets)

        # 4. schema constraints (ranges, allowed values)
        if self.schema is not None:
            changes.extend(self._fix_constraints(work, flag))

        # 5. missing values
        for col in work.columns:
            mask = work[col].isna().to_numpy()
            if not mask.any():
                continue
            changes.extend(self._fix_missing(work, col, mask, dtypes[col], flag, dropped))

        if self.llm is not None and flagged:
            changes.extend(self._llm_suggest(work, flagged))

        changes = _merge_cells(changes)
        for ch in changes:
            ch.index = index[ch.row]
        flagged_rows = {f.row for f in flagged}

        # restore integer columns that became float during fixing
        for col, dt in dtypes.items():
            if dt == DataType.INTEGER and pd.api.types.is_float_dtype(work[col]):
                vals = work[col].dropna()
                if len(vals) and whole_numbers(vals):
                    work[col] = work[col].astype("Int64")

        if self.policy.flag_column:
            work[self.policy.flag_column] = [r in flagged_rows for r in range(n)]
        keep = [r for r in range(n) if r not in dropped]
        out = work.iloc[keep].copy()
        out.index = [index[r] for r in keep]
        return RemediationResult(out, original, changes, dropped, flagged)

    # ------------------------------------------------------------------
    def _fix_outliers(
        self,
        work,
        col,
        mask,
        reasons,
        flag,
        dropped,
        sources=None,
        dtype: DataType | None = None,
        groups: pd.Series | None = None,
        group_label: str = "",
    ) -> list[Change]:
        pol = self.policy.for_column(col)
        action = pol.outlier
        rows = np.flatnonzero(mask)
        why = {r: reasons.get((r, col), "outlier") for r in rows.tolist()}
        src = {r: (sources or {}).get((r, col)) for r in rows.tolist()}
        if action == "keep":
            return []
        if action == "flag":
            for r in rows.tolist():
                flag(r, col, why[r], src[r])
            return []
        if action == "drop":
            for r in rows.tolist():
                dropped.setdefault(r, f"outlier in {col}: {why[r]}")
            return []
        numeric_col = pd.api.types.is_numeric_dtype(work[col]) and not pd.api.types.is_bool_dtype(
            work[col]
        )
        if not numeric_col and not (dtype is not None and dtype.is_numeric):
            for r in rows.tolist():
                flag(r, col, why[r], src[r])
            return []
        # Strategies work on a numeric copy, so a column whose unparseable cells
        # were kept as text (invalid: drop/flag/keep) still gets its outliers fixed;
        # only the changed cells are written back.
        target = work
        if not numeric_col:
            target = pd.DataFrame(
                {col: coerce_series(work[col], DataType.FLOAT)[0].astype(float)}
            ).reset_index(drop=True)
        strategy: Strategy
        if action == "cap":
            strategy = Cap(pol.cap_k, groups=groups, group_label=group_label or "group")
            if self.schema is not None and col in self.schema.fields:
                fmin = self.schema.fields[col].min
                if isinstance(fmin, (int, float)) and fmin >= 0:
                    strategy.non_negative = True
        elif action == "winsorize":
            strategy = Winsorize()
        elif action == "clip":
            strategy = Clip(pol.min, pol.max)
        elif action in ("median", "mean"):
            out = SetNull().apply(target, col, mask, "outlier replaced")
            out += Impute(action, groups=groups).apply(target, col, mask, "outlier replaced")
            return self._write_back(work, target, col, _merge_chain(out))
        else:  # null
            return self._write_back(
                work, target, col, SetNull().apply(target, col, mask, "outlier removed")
            )
        changes = self._write_back(work, target, col, strategy.apply(target, col, mask))
        changed = {c.row for c in changes}
        for c in changes:
            c.reason = f"{c.reason}; detected: {why[c.row]}"
        # values a robust cap cannot move (e.g. contextual anomalies) or should not
        # move (far out of range, wrong sign) go to review
        skipped = getattr(strategy, "skipped", {})
        for r in rows.tolist():
            if r not in changed:
                note = skipped.get(r) or f"not auto-fixable by {strategy.name}"
                flag(r, col, f"{why[r]} ({note})", src[r])
        return changes

    @staticmethod
    def _write_back(work, target, col, changes: list[Change]) -> list[Change]:
        """Copy changed cells from a numeric working copy into ``work``."""
        if target is work:
            return changes
        if changes and pd.api.types.is_string_dtype(work[col].dtype):
            # The column still holds unparseable text (the invalid policy kept
            # it); pandas 3's strict string dtype refuses numbers, so hold
            # mixed values like pandas 2 does.
            work[col] = work[col].astype(object)
        pos = work.columns.get_loc(col)
        for c in changes:
            c.before = work.iat[c.row, pos]
            work.iat[c.row, pos] = c.after
        return changes

    def _fix_constraints(self, work, flag) -> list[Change]:
        changes: list[Change] = []
        assert self.schema is not None
        for col, fld in self.schema.fields.items():
            if col not in work.columns:
                continue
            pol = self.policy.for_column(col)
            protected = np.array(
                [(r, col) in self._protected for r in range(len(work))], dtype=bool
            )
            if fld.dtype == DataType.DATETIME and (fld.min is not None or fld.max is not None):
                self._flag_date_range(work, col, fld, protected, flag)
            if fld.dtype.is_numeric and (fld.min is not None or fld.max is not None):
                nums = pd.to_numeric(work[col], errors="coerce")
                lo = fld.min if fld.min is not None else -np.inf
                hi = fld.max if fld.max is not None else np.inf
                mask = ((nums < lo) | (nums > hi)).to_numpy() & ~protected
                if mask.any():
                    if pol.outlier in ("flag", "keep"):
                        for r in np.flatnonzero(mask).tolist():
                            flag(
                                r,
                                col,
                                f"{work[col].iloc[r]} outside [{fld.min}, {fld.max}]",
                                "schema",
                            )
                    else:
                        changes.extend(
                            Clip(fld.min, fld.max).apply(work, col, mask, "schema range")
                        )
            if fld.allowed:
                changes.extend(normalise_categories(work, col, fld.allowed))
                bad = work[col].notna() & ~work[col].isin(fld.allowed) & ~protected
                for r in np.flatnonzero(bad.to_numpy()).tolist():
                    flag(r, col, f"{work[col].iloc[r]!r} not an allowed value", "schema")
        return changes

    @staticmethod
    def _flag_date_range(work, col, fld, protected, flag) -> None:
        """Dates outside the schema range go to review: a wrong date cannot be
        repaired by clipping without inventing one."""
        from anomalyguard.schema.validator import _now_like

        ts = work[col]
        if not pd.api.types.is_datetime64_any_dtype(ts):
            ts = pd.to_datetime(ts, errors="coerce", format="mixed")
        present = ts.notna().to_numpy() & ~protected
        if fld.max is not None:
            if str(fld.max).strip().lower() == "now":
                hi = _now_like(ts) + pd.Timedelta(days=1)
                why = "date is in the future"
            else:
                hi = pd.Timestamp(fld.max)
                why = f"date after the schema maximum {fld.max}"
            for r in np.flatnonzero(present & (ts > hi).to_numpy()).tolist():
                flag(r, col, f"{work[col].iloc[r]} - {why}", "schema")
        if fld.min is not None:
            lo = pd.Timestamp(fld.min)
            for r in np.flatnonzero(present & (ts < lo).to_numpy()).tolist():
                flag(
                    r,
                    col,
                    f"{work[col].iloc[r]} - date before the schema minimum {fld.min}",
                    "schema",
                )

    def _id_like(self, col: str) -> bool:
        if _is_id_like(col):
            return True
        if self.schema is None:
            return False
        fld = self.schema.fields.get(col)
        return bool(fld is not None and fld.unique) or col in (self.schema.primary_key or [])

    def _fix_missing(self, work, col, mask, dtype, flag, dropped) -> list[Change]:
        pol = self.policy.for_column(col)
        action = pol.missing
        note = ""
        if action == "auto":
            if self._id_like(col) or dtype in (
                DataType.STRING,
                DataType.DATETIME,
                DataType.UNKNOWN,
            ):
                action = "flag"
            elif dtype.is_numeric:
                action = "median"
            else:
                action = "mode"
        elif action not in ("keep", "flag", "drop"):
            # Identifiers are never invented, and numeric fills do not apply to
            # text, categories or dates: those cells go to review instead.
            if self._id_like(col):
                action, note = "flag", f" (identifier column: not filled by {pol.missing})"
            elif action in ("mean", "median", "interpolate") and not dtype.is_numeric:
                action, note = (
                    "flag",
                    f" ({pol.missing} needs a numeric column; {col} is {dtype.value})",
                )
        if action == "keep":
            return []
        rows = np.flatnonzero(mask)
        if action == "flag":
            for r in rows.tolist():
                flag(r, col, f"missing value{note}", "missing")
            return []
        if action == "drop":
            for r in rows.tolist():
                dropped.setdefault(r, f"missing {col}")
            return []
        return Impute(action, pol.constant).apply(work, col, mask, "missing value")

    def _llm_suggest(self, work: pd.DataFrame, flagged: list[FlaggedItem]) -> list[Change]:
        changes: list[Change] = []
        for item in flagged[: self.llm_max_items]:
            if item.column is None:
                continue
            record = work.iloc[item.row].to_dict()
            try:
                sug = self.llm.suggest(record, item.column, item.value, item.reason)
            except Exception as exc:  # network errors etc. must not break remediation
                item.suggestion_rationale = f"LLM unavailable: {exc}"
                continue
            if sug is None:
                continue
            item.suggestion = sug.value
            item.suggestion_confidence = sug.confidence
            item.suggestion_rationale = sug.rationale
            if self.llm_auto_apply and sug.confidence >= self.llm_min_confidence:
                before = work.iloc[item.row][item.column]
                work.iloc[item.row, work.columns.get_loc(item.column)] = sug.value
                item.applied = True
                changes.append(
                    Change(
                        item.row,
                        item.column,
                        before,
                        sug.value,
                        "llm",
                        sug.rationale or "",
                        sug.confidence,
                        item.index,
                    )
                )
        return changes


def _merge_cells(changes: list[Change]) -> list[Change]:
    """One record per cell: when several steps changed the same cell (e.g. a cap
    and then a schema clip), keep the original value as ``before``, the final
    value as ``after`` and name every strategy."""
    merged: dict[tuple[int, str | None], Change] = {}
    out: list[Change] = []
    for c in changes:
        key = (c.row, c.column)
        if c.column is None or key not in merged:
            merged[key] = c
            out.append(c)
            continue
        first = merged[key]
        first.after = c.after
        if c.strategy not in first.strategy.split("+"):
            first.strategy = f"{first.strategy}+{c.strategy}"
        first.reason = f"{first.reason}; then {c.reason}" if c.reason else first.reason
        first.confidence = min(first.confidence, c.confidence)
    return out


def _merge_chain(changes: list[Change]) -> list[Change]:
    """Collapse set_null + impute on the same cell into one change."""
    first: dict[tuple[int, str | None], Change] = {}
    for c in changes:
        key = (c.row, c.column)
        if key in first:
            first[key].after = c.after
            first[key].strategy = c.strategy
            first[key].confidence = c.confidence
        else:
            first[key] = c
    return list(first.values())
