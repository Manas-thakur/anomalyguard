"""Combine detector results into a per-row anomaly report with reasons."""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from anomalyguard.detect.base import DetectionResult, Finding


@dataclass
class AnomalyReport:
    """Anomalies found in one dataset by one or more detectors.

    ``combine`` decides when a row counts as anomalous: ``any`` detector,
    ``vote`` (at least ``min_votes`` detectors) or ``all`` detectors.
    """

    n_rows: int
    results: list[DetectionResult]
    index: list[Any] = field(default_factory=list)
    combine: Literal["any", "vote", "all"] = "any"
    min_votes: int = 1
    #: grouped detector name -> its group columns (used by group-aware remediation)
    groups: dict[str, list[str]] = field(default_factory=dict)
    #: notes about how the data was analysed (gaps in a time series, clamped votes, ...)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.index:
            self.index = list(range(self.n_rows))

    def tail(self, start: int) -> AnomalyReport:
        """A report for rows ``start..n_rows`` only (row numbers restart at 0).

        Used for incremental runs, where detectors are fitted on reference
        rows plus the new batch but only the new rows are reported.
        """
        results = []
        for r in self.results:
            findings = []
            for f in r.findings:
                if f.row >= start:
                    f = copy.copy(f)
                    f.row -= start
                    findings.append(f)
            results.append(
                DetectionResult(
                    detector=r.detector,
                    raw_scores=r.raw_scores[start:],
                    scores=r.scores[start:],
                    labels=r.labels[start:],
                    threshold=r.threshold,
                    columns=r.columns,
                    findings=findings,
                    column_scores=None if r.column_scores is None else r.column_scores[start:],
                )
            )
        return AnomalyReport(
            n_rows=self.n_rows - start,
            results=results,
            index=list(self.index[start:]),
            combine=self.combine,
            min_votes=self.min_votes,
            groups=dict(self.groups),
            warnings=list(self.warnings),
        )

    def group_columns(self, column: str) -> list[str] | None:
        """Group columns of a grouped detector that flagged cells in ``column``."""
        names = {f.detector for r in self.results for f in r.findings if f.column == column}
        for name, cols in self.groups.items():
            if name in names:
                return cols
        return None

    @property
    def detectors(self) -> list[str]:
        return [r.detector for r in self.results]

    @property
    def votes(self) -> np.ndarray:
        if not self.results:
            return np.zeros(self.n_rows, dtype=int)
        return np.vstack([r.labels for r in self.results]).sum(axis=0)

    @property
    def flagged(self) -> np.ndarray:
        v = self.votes
        if self.combine == "all":
            return v == len(self.results)
        if self.combine == "vote":
            return v >= self.min_votes
        return v >= 1

    @property
    def row_scores(self) -> np.ndarray:
        if not self.results:
            return np.zeros(self.n_rows)
        return np.vstack([r.scores for r in self.results]).max(axis=0)

    @property
    def anomalous_rows(self) -> list[int]:
        return np.flatnonzero(self.flagged).tolist()

    @property
    def n_anomalies(self) -> int:
        return int(self.flagged.sum())

    @property
    def anomaly_rate(self) -> float:
        return self.n_anomalies / self.n_rows if self.n_rows else 0.0

    @property
    def findings(self) -> list[Finding]:
        flagged = self.flagged
        out = [f for r in self.results for f in r.findings if flagged[f.row]]
        return sorted(out, key=lambda f: (f.row, -f.score))

    def column_mask(self, columns: list[str]) -> pd.DataFrame:
        """Positional boolean frame of cells attributed to an anomaly."""
        pos = {c: i for i, c in enumerate(columns)}
        mask = np.zeros((self.n_rows, len(columns)), dtype=bool)
        for f in self.findings:
            if f.column in pos:
                mask[f.row, pos[f.column]] = True
        return pd.DataFrame(mask, columns=columns)

    def rows_without_column(self) -> list[int]:
        """Flagged rows where no detector could attribute a specific column."""
        with_col = {f.row for f in self.findings if f.column is not None}
        return [r for r in self.anomalous_rows if r not in with_col]

    def counts_by_detector(self) -> dict[str, int]:
        return {r.detector: r.n_anomalies for r in self.results}

    def counts_by_column(self) -> dict[str, int]:
        rows_by_col: dict[str, set[int]] = {}
        for f in self.findings:
            rows_by_col.setdefault(f.column or "(row)", set()).add(f.row)
        return {k: len(v) for k, v in sorted(rows_by_col.items())}

    def records(self, limit: int | None = None) -> list[dict[str, Any]]:
        """One entry per anomalous row, highest score first."""
        by_row: dict[int, list[Finding]] = {}
        for f in self.findings:
            by_row.setdefault(f.row, []).append(f)
        scores = self.row_scores
        votes = self.votes
        rows = sorted(self.anomalous_rows, key=lambda r: -scores[r])
        if limit is not None:
            rows = rows[:limit]
        out = []
        for r in rows:
            fs = by_row.get(r, [])
            idx = self.index[r]
            idx = idx.item() if hasattr(idx, "item") else idx
            out.append(
                {
                    "row": r,
                    "index": idx if isinstance(idx, (int, float, str)) else str(idx),
                    "score": round(float(scores[r]), 4),
                    "votes": int(votes[r]),
                    "detectors": sorted({f.detector for f in fs}),
                    "columns": sorted({f.column for f in fs if f.column}),
                    "reasons": [f.reason for f in fs],
                }
            )
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "n_rows": self.n_rows,
            "n_anomalies": self.n_anomalies,
            "anomaly_rate": round(self.anomaly_rate, 6),
            "combine": self.combine,
            "detectors": self.counts_by_detector(),
            "columns": self.counts_by_column(),
        }

    def to_dict(self, limit: int | None = None) -> dict[str, Any]:
        out = {
            "summary": self.summary(),
            "thresholds": {r.detector: r.threshold for r in self.results},
            "anomalies": self.records(limit),
            "findings": [f.to_dict() for f in self.findings][: limit * 5 if limit else None],
        }
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([f.to_dict() for f in self.findings])

    def to_json(self, path: str | Path | None = None, limit: int | None = None) -> str:
        text = json.dumps(self.to_dict(limit), indent=2, default=str)
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
        return text

    def reason_counts(self) -> Counter:
        return Counter(f.detector for f in self.findings)
