"""Human-readable before/after report for a remediation run."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from anomalyguard.detect.base import fmt

if TYPE_CHECKING:
    from anomalyguard.remediate.pipeline import RemediationResult


def _col_stats(s: pd.Series) -> dict[str, Any]:
    nums = pd.to_numeric(s, errors="coerce")
    out: dict[str, Any] = {"nulls": int(s.isna().sum())}
    if nums.notna().sum() >= max(1, 0.9 * s.notna().sum()):
        x = nums.dropna()
        if len(x):
            out.update(
                mean=float(x.mean()),
                std=float(x.std(ddof=0)),
                min=float(x.min()),
                max=float(x.max()),
            )
    return out


class RemediationReport:
    """Summary, per-column before/after statistics and a cell-level diff."""

    def __init__(self, result: RemediationResult):
        self.result = result

    def summary(self) -> dict[str, Any]:
        r = self.result
        return {
            "rows_in": len(r.original),
            "rows_out": len(r.data),
            "rows_dropped": len(r.dropped),
            "cells_changed": r.n_changed_cells,
            "rows_flagged_for_review": len({f.row for f in r.flagged}),
            "changes_by_strategy": dict(Counter(c.strategy for c in r.changes)),
            "changes_by_column": dict(Counter(c.column for c in r.changes if c.column)),
            "drop_reasons": dict(Counter(v.split(":")[0] for v in r.dropped.values())),
        }

    def column_stats(self) -> dict[str, dict[str, Any]]:
        r = self.result
        out = {}
        changed_cols = {c.column for c in r.changes if c.column}
        for col in r.original.columns:
            if col not in changed_cols:
                continue
            out[col] = {
                "before": _col_stats(r.original[col]),
                "after": _col_stats(r.data[col]) if col in r.data else {},
            }
        return out

    def diff(self) -> pd.DataFrame:
        return pd.DataFrame([c.to_dict() for c in self.result.changes])

    def to_dict(self, max_changes: int | None = 1000) -> dict[str, Any]:
        r = self.result
        changes = r.changes if max_changes is None else r.changes[:max_changes]
        return {
            "summary": self.summary(),
            "column_stats": self.column_stats(),
            # the change list is capped; these say how many there are in total
            "total_changes": len(r.changes),
            "truncated": len(changes) < len(r.changes),
            "changes": [c.to_dict() for c in changes],
            "dropped": [
                {"row": k, "index": _plain(r.original.index[k]), "reason": v}
                for k, v in sorted(r.dropped.items())
            ],
            "flagged": [f.to_dict() for f in r.flagged],
        }

    def to_json(self, path: str | Path | None = None) -> str:
        text = json.dumps(self.to_dict(), indent=2, default=str)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_markdown(self, max_rows: int = 50) -> str:
        s = self.summary()
        lines = [
            "# Remediation report",
            "",
            f"- Rows: {s['rows_in']} in, {s['rows_out']} out ({s['rows_dropped']} dropped)",
            f"- Cells changed: {s['cells_changed']}",
            f"- Rows flagged for review: {s['rows_flagged_for_review']}",
            "",
        ]
        if s["changes_by_strategy"]:
            lines += ["## Changes by strategy", "", "| Strategy | Cells |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in sorted(s["changes_by_strategy"].items())]
            lines.append("")
        stats = self.column_stats()
        if stats:
            lines += [
                "## Column statistics (before -> after)",
                "",
                "| Column | Nulls | Mean | Std | Min | Max |",
                "|---|---|---|---|---|---|",
            ]
            for col, st in stats.items():
                b, a = st["before"], st["after"]

                def pair(key: str, b=b, a=a) -> str:
                    if b.get(key) is None and a.get(key) is None:
                        return "-"
                    return f"{fmt(b.get(key))} -> {fmt(a.get(key))}"

                lines.append(
                    f"| {col} | {pair('nulls')} | {pair('mean')} | {pair('std')} | {pair('min')} | {pair('max')} |"
                )
            lines.append("")
        if self.result.changes:
            lines += [
                "## Cell changes",
                "",
                "| Row | Column | Before | After | Strategy | Reason |",
                "|---|---|---|---|---|---|",
            ]
            for c in self.result.changes[:max_rows]:
                d = c.to_dict()
                lines.append(
                    f"| {d['index']} | {d['column']} | {_show(d['before'])} | {_show(d['after'])} | {d['strategy']} | {_md(d['reason'])} |"
                )
            if len(self.result.changes) > max_rows:
                lines.append(f"\n... {len(self.result.changes) - max_rows} more changes")
            lines.append("")
        if self.result.dropped:
            lines += ["## Dropped rows", "", "| Row | Reason |", "|---|---|"]
            for k, v in list(sorted(self.result.dropped.items()))[:max_rows]:
                lines.append(f"| {_plain(self.result.original.index[k])} | {_md(v)} |")
            lines.append("")
        if self.result.flagged:
            lines += [
                "## Flagged for review",
                "",
                "| Row | Column | Value | Reason |",
                "|---|---|---|---|",
            ]
            for f in self.result.flagged[:max_rows]:
                d = f.to_dict()
                lines.append(
                    f"| {d['index']} | {d['column'] or '-'} | {_show(d['value']) if d['column'] else '-'} | {_md(d['reason'])} |"
                )
            lines.append("")
        return "\n".join(lines)


def _show(v: Any) -> str:
    """A cell value for the report; missing cells are spelled out because "NA"
    can be a real value (e.g. a region code)."""
    return "(missing)" if v is None else _md(fmt(v))


def _md(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def _plain(v: Any) -> Any:
    if isinstance(v, (np.generic,)):
        return v.item()
    return v
