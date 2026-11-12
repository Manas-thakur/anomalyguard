"""Vectorised schema validation producing row/column level errors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.schema.coercion import coerce_series
from anomalyguard.schema.registry import DataType, Schema


@dataclass
class FieldError:
    row: int  # positional row number
    column: str
    rule: str
    value: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "column": self.column,
            "rule": self.rule,
            "value": _jsonable(self.value),
            "message": self.message,
        }


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v if isinstance(v, (int, str, bool)) else str(v)


@dataclass
class ValidationReport:
    n_rows: int
    errors: list[FieldError] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    coerced: pd.DataFrame | None = None

    @property
    def passed(self) -> bool:
        return not self.errors and not self.schema_errors

    @property
    def invalid_rows(self) -> list[int]:
        return sorted({e.row for e in self.errors})

    @property
    def n_invalid_rows(self) -> int:
        return len({e.row for e in self.errors})

    def counts_by_rule(self) -> dict[str, int]:
        return dict(Counter(e.rule for e in self.errors))

    def counts_by_column(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for e in self.errors:
            out.setdefault(e.column, {}).setdefault(e.rule, 0)
            out[e.column][e.rule] += 1
        return out

    def error_mask(self, columns: list[str], rules: set[str] | None = None) -> pd.DataFrame:
        """Boolean frame (positional rows) marking cells with errors."""
        mask = np.zeros((self.n_rows, len(columns)), dtype=bool)
        pos = {c: i for i, c in enumerate(columns)}
        for e in self.errors:
            if e.column in pos and (rules is None or e.rule in rules):
                mask[e.row, pos[e.column]] = True
        return pd.DataFrame(mask, columns=columns)

    def to_dict(self, max_errors: int | None = 1000) -> dict[str, Any]:
        errs = self.errors if max_errors is None else self.errors[:max_errors]
        return {
            "passed": self.passed,
            "n_rows": self.n_rows,
            "n_invalid_rows": self.n_invalid_rows,
            "n_errors": len(self.errors),
            "schema_errors": self.schema_errors,
            "counts_by_rule": self.counts_by_rule(),
            "counts_by_column": self.counts_by_column(),
            "errors": [e.to_dict() for e in errs],
        }


class SchemaValidator:
    """Validate a DataFrame against a :class:`Schema`.

    Checks types (via coercion), nullability, numeric ranges, string length,
    regex patterns, allowed values (enums), per-column uniqueness and the
    primary key.
    """

    def __init__(self, schema: Schema, strict: bool | None = None):
        self.schema = schema
        self.strict = schema.strict if strict is None else strict

    def validate(self, df: pd.DataFrame) -> ValidationReport:
        df = df.reset_index(drop=True)
        report = ValidationReport(n_rows=len(df))
        coerced = df.copy()

        for name in self.schema.fields:
            if name not in df.columns:
                report.schema_errors.append(f"missing column: {name}")
        extra = [c for c in df.columns if c not in self.schema.fields]
        if extra and self.strict:
            report.schema_errors.append(f"unexpected columns: {extra}")

        for name, fld in self.schema.fields.items():
            if name not in df.columns:
                continue
            raw = df[name]
            values, failed = coerce_series(raw, fld.dtype)
            coerced[name] = values
            self._add(
                report,
                failed,
                raw,
                name,
                "type",
                lambda v, f=fld: f"cannot convert {v!r} to {f.dtype.value}",
            )

            if not fld.nullable:
                nulls = raw.isna()
                self._add(
                    report,
                    nulls,
                    raw,
                    name,
                    "not_null",
                    lambda v: "missing value in non-nullable column",
                )

            present = values.notna()
            if fld.dtype.is_numeric:
                num = values.astype(float)
                if fld.min is not None:
                    self._add(
                        report,
                        present & (num < fld.min),
                        raw,
                        name,
                        "min",
                        lambda v, m=fld.min: f"{v} < min {m}",
                    )
                if fld.max is not None:
                    self._add(
                        report,
                        present & (num > fld.max),
                        raw,
                        name,
                        "max",
                        lambda v, m=fld.max: f"{v} > max {m}",
                    )
            elif fld.dtype == DataType.DATETIME and (fld.min is not None or fld.max is not None):
                if fld.min is not None:
                    lo = pd.Timestamp(fld.min)
                    self._add(
                        report,
                        present & (values < lo),
                        raw,
                        name,
                        "min",
                        lambda v, m=lo: f"{v} before {m}",
                    )
                if fld.max is not None:
                    hi = pd.Timestamp(fld.max)
                    self._add(
                        report,
                        present & (values > hi),
                        raw,
                        name,
                        "max",
                        lambda v, m=hi: f"{v} after {m}",
                    )

            if fld.min_length is not None or fld.max_length is not None or fld.pattern:
                as_str = raw.where(raw.isna(), raw.astype(str))
                lengths = as_str.str.len()
                if fld.min_length is not None:
                    self._add(
                        report,
                        present & (lengths < fld.min_length),
                        raw,
                        name,
                        "min_length",
                        lambda v, m=fld.min_length: f"length < {m}",
                    )
                if fld.max_length is not None:
                    self._add(
                        report,
                        present & (lengths > fld.max_length),
                        raw,
                        name,
                        "max_length",
                        lambda v, m=fld.max_length: f"length > {m}",
                    )
                if fld.pattern:
                    ok = (
                        as_str.str.fullmatch(fld.pattern)
                        .astype("boolean")
                        .fillna(True)
                        .astype(bool)
                    )
                    self._add(
                        report,
                        present & ~ok,
                        raw,
                        name,
                        "pattern",
                        lambda v, p=fld.pattern: f"{v!r} does not match /{p}/",
                    )

            if fld.allowed is not None:
                allowed = set(fld.allowed) | {str(a) for a in fld.allowed}
                bad = present & ~raw.map(lambda v, a=allowed: v in a or str(v) in a).astype(bool)
                self._add(
                    report, bad, raw, name, "allowed", lambda v, a=fld.allowed: f"{v!r} not in {a}"
                )

            if fld.unique:
                dup = present & values.duplicated(keep=False)
                self._add(report, dup, raw, name, "unique", lambda v: f"duplicate value {v!r}")

        pk = [c for c in (self.schema.primary_key or []) if c in df.columns]
        if pk:
            dup = df.duplicated(subset=pk, keep="first")
            self._add(
                report,
                dup,
                df[pk[0]],
                pk[0],
                "primary_key",
                lambda v: f"duplicate primary key {v!r}",
            )

        report.errors.sort(key=lambda e: (e.row, e.column))
        report.coerced = coerced
        return report

    @staticmethod
    def _add(
        report: ValidationReport, mask: pd.Series, raw: pd.Series, column: str, rule: str, msg
    ) -> None:
        mask = mask.fillna(False).astype(bool).to_numpy()
        for row in np.flatnonzero(mask):
            v = raw.iloc[row]
            report.errors.append(FieldError(int(row), column, rule, v, msg(v)))
