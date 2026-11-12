"""High-level ``run_detectors`` helper used by the CLI, API and pipeline."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from anomalyguard.detect.base import Detector
from anomalyguard.detect.registry import build_detector
from anomalyguard.detect.report import AnomalyReport

DEFAULT_METHODS = ["mad", "iforest"]


def run_detectors(
    df: pd.DataFrame,
    methods: list[str | dict[str, Any] | Detector] | str | None = None,
    columns: list[str] | None = None,
    group_by: str | list[str] | None = None,
    time_column: str | None = None,
    combine: Literal["any", "vote", "all"] = "any",
    min_votes: int = 1,
    threshold_multipliers: dict[str, float] | None = None,
    threshold_scale: float = 1.0,
) -> AnomalyReport:
    """Fit each detector on ``df`` and score it, returning an :class:`AnomalyReport`.

    ``methods`` may be names (``"mad,iforest"``), spec dicts or Detector instances.
    ``columns``/``group_by`` apply to specs that do not set them. With
    ``time_column`` the frame is sorted by time before detection (results are
    mapped back to the original row order). ``threshold_scale`` multiplies
    every detector's threshold (below 1 flags more, above 1 flags less).
    """
    if methods is None:
        methods = list(DEFAULT_METHODS)
    if isinstance(methods, str):
        methods = [m.strip() for m in methods.split(",") if m.strip()]

    original_index = list(df.index)
    work = df.reset_index(drop=True)
    order = None
    if time_column and time_column in work.columns:
        ts = pd.to_datetime(work[time_column], errors="coerce", format="mixed")
        order = ts.sort_values(kind="stable").index.to_numpy()
        work = work.iloc[order].reset_index(drop=True)

    results = []
    for spec in methods:
        if isinstance(spec, (str, dict)):
            spec = {"method": spec} if isinstance(spec, str) else dict(spec)
            if columns and "columns" not in spec:
                spec["columns"] = columns
            if group_by and "group_by" not in spec:
                spec["group_by"] = group_by
        det = build_detector(spec)
        det.fit(work)
        if threshold_multipliers:
            base_name = det.name.split("(")[0]
            det.threshold_multiplier = threshold_multipliers.get(
                det.name, threshold_multipliers.get(base_name, 1.0)
            )
        if threshold_scale != 1.0:
            det.threshold_multiplier *= float(threshold_scale)
        res = det.detect(work)
        if order is not None:
            # map sorted positions back to the original positions
            res.raw_scores = _unsort(res.raw_scores, order)
            res.scores = _unsort(res.scores, order)
            res.labels = _unsort(res.labels, order)
            if res.column_scores is not None:
                res.column_scores = _unsort(res.column_scores, order)
            for f in res.findings:
                f.row = int(order[f.row])
        for f in res.findings:
            f.index = original_index[f.row]
        results.append(res)

    return AnomalyReport(
        n_rows=len(df), results=results, index=original_index, combine=combine, min_votes=min_votes
    )


def _unsort(arr, order):
    out = arr.copy()
    out[order] = arr
    return out
