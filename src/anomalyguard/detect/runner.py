"""High-level ``run_detectors`` helper used by the CLI, API and pipeline."""

from __future__ import annotations

import logging
import warnings
from typing import Any, Literal

import numpy as np
import pandas as pd

from anomalyguard.detect.base import DetectionResult, Detector
from anomalyguard.detect.contextual import GroupedDetector
from anomalyguard.detect.registry import build_detector
from anomalyguard.detect.report import AnomalyReport

DEFAULT_METHODS = ["mad", "iforest"]
log = logging.getLogger("anomalyguard.detect")

# A regular grid is only built when it stays reasonably dense.
MAX_GRID_FACTOR = 4


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
    mapped back to the original row order), and time-series detectors run on a
    regular time grid: when the timestamps have gaps, the missing points are
    inserted as empty values so seasonal phases and windows follow the clock,
    not the row count. ``threshold_scale`` multiplies every detector's
    threshold (below 1 flags more, above 1 flags less).
    """
    if methods is None:
        methods = list(DEFAULT_METHODS)
    if isinstance(methods, str):
        methods = [m.strip() for m in methods.split(",") if m.strip()]
    if not methods:
        raise ValueError("No detectors given (e.g. methods=['mad', 'iforest'])")
    notes: list[str] = []
    min_votes = _check_votes(combine, min_votes, len(methods), notes)

    original_index = list(df.index)
    work = df.reset_index(drop=True)
    order = None
    grid = None
    if time_column:
        if time_column not in work.columns:
            raise KeyError(
                f"Time column '{time_column}' not found. Columns: {', '.join(map(str, work.columns))}"
            )
        ts = _timestamps(work[time_column])
        if ts.notna().sum() == 0:
            raise ValueError(f"Time column '{time_column}' has no parseable timestamps")
        order = ts.sort_values(kind="stable").index.to_numpy()
        work = work.iloc[order].reset_index(drop=True)
        grid = _regular_grid(ts.iloc[order].reset_index(drop=True), time_column, notes)

    results = []
    groups: dict[str, list[str]] = {}
    for spec in methods:
        if isinstance(spec, (str, dict)):
            spec = {"method": spec} if isinstance(spec, str) else dict(spec)
            if columns and "columns" not in spec:
                spec["columns"] = columns
            if group_by and "group_by" not in spec:
                spec["group_by"] = group_by
        det = build_detector(spec)
        if isinstance(det, GroupedDetector):
            groups[det.name] = list(det.group_by)
        temporal = getattr(det, "temporal", False)
        with warnings.catch_warnings():
            # all-missing or constant columns make numpy warn; results are still defined
            warnings.simplefilter("ignore", RuntimeWarning)
            if temporal and grid is not None:
                res = _detect_on_grid(det, work, grid, threshold_multipliers, threshold_scale)
            else:
                res = _fit_detect(det, work, threshold_multipliers, threshold_scale)
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

    for note in notes:
        log.warning(note)
    return AnomalyReport(
        n_rows=len(df),
        results=results,
        index=original_index,
        combine=combine,
        min_votes=min_votes,
        groups=groups,
        warnings=notes,
    )


def _check_votes(combine: str, min_votes: int, n_detectors: int, notes: list[str]) -> int:
    if combine not in ("any", "vote", "all"):
        raise ValueError(f"combine must be any, vote or all (got {combine!r})")
    if combine != "vote":
        return min_votes
    if min_votes < 1:
        raise ValueError(f"min_votes must be at least 1 (got {min_votes})")
    if n_detectors == 1:
        notes.append("combine=vote with a single detector is the same as combine=any")
        return 1
    if min_votes > n_detectors:
        notes.append(
            f"min_votes={min_votes} is more than the {n_detectors} detectors; "
            f"using min_votes={n_detectors} (all must agree)"
        )
        return n_detectors
    return min_votes


def _timestamps(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    if pd.api.types.is_numeric_dtype(s):
        return pd.Series(pd.NaT, index=s.index) if s.isna().all() else s.astype(float)
    return pd.to_datetime(s, errors="coerce", format="mixed")


def _fit_detect(
    det: Detector,
    frame: pd.DataFrame,
    multipliers: dict[str, float] | None,
    scale: float,
) -> DetectionResult:
    det.fit(frame)
    if multipliers:
        base_name = det.name.split("(")[0]
        det.threshold_multiplier = multipliers.get(det.name, multipliers.get(base_name, 1.0))
    if scale != 1.0:
        det.threshold_multiplier *= float(scale)
    return det.detect(frame)


class _Grid:
    """Positions of the (sorted) rows on a regular time grid."""

    def __init__(self, rows: np.ndarray, slots: np.ndarray, size: int):
        self.rows = rows  # sorted row positions that have a timestamp
        self.slots = slots  # their slot on the grid
        self.size = size


def _fmt_step(step: Any) -> str:
    if isinstance(step, pd.Timedelta):
        return str(step).replace("0 days ", "").removesuffix(".000000")
    return f"{step:g}"


def _regular_grid(ts: pd.Series, name: str, notes: list[str]) -> _Grid | None:
    """Map sorted timestamps to slots of a regular grid when the series has gaps.

    Returns None when the series is already regular (row order is the clock)
    or cannot be put on a grid (duplicate or irregular timestamps).
    """
    valid = np.flatnonzero(ts.notna().to_numpy())
    t = ts.iloc[valid]
    if len(t) < 3:
        return None
    if t.duplicated().any():
        notes.append(
            f"{name}: repeated timestamps (several series in one column?); time-series "
            "detectors use row order. Use group_by for one series per device/entity."
        )
        return None
    diffs = t.diff().iloc[1:]
    step = diffs.median()
    if not step or (isinstance(step, pd.Timedelta) and step <= pd.Timedelta(0)):
        return None
    offsets = (t - t.iloc[0]) / step
    slots = np.rint(offsets.to_numpy(dtype=float)).astype(np.int64)
    if (
        len(np.unique(slots)) != len(slots)
        or np.abs(offsets.to_numpy(dtype=float) - slots).max() > 0.25
    ):
        notes.append(
            f"{name}: timestamps are not evenly spaced (typical step {_fmt_step(step)}); "
            "time-series detectors use row order"
        )
        return None
    size = int(slots[-1]) + 1
    missing = size - len(t)
    if missing == 0:
        return None
    if size > MAX_GRID_FACTOR * len(t):
        notes.append(
            f"{name}: {missing} missing points between {len(t)} readings (step "
            f"{_fmt_step(step)}) - too sparse for a regular grid; time-series detectors use row order"
        )
        return None
    gaps = diffs[diffs > 1.5 * step]
    largest = _fmt_step(gaps.max()) if len(gaps) else _fmt_step(step)
    notes.append(
        f"{name}: {len(gaps)} gap(s) in the time series ({missing} missing points, largest "
        f"{largest}); time-series detectors run on a regular {_fmt_step(step)} grid with the "
        "missing points left empty"
    )
    return _Grid(valid, slots, size)


def _detect_on_grid(
    det: Detector,
    work: pd.DataFrame,
    grid: _Grid,
    multipliers: dict[str, float] | None,
    scale: float,
) -> DetectionResult:
    """Run a time-series detector on the regular grid and map results back to rows."""
    framed = work.iloc[grid.rows].copy()
    framed.index = grid.slots
    framed = framed.reindex(range(grid.size))
    res = _fit_detect(det, framed, multipliers, scale)
    n = len(work)

    def back(arr: np.ndarray, fill: Any) -> np.ndarray:
        out = np.full((n, *arr.shape[1:]), fill, dtype=arr.dtype)
        out[grid.rows] = arr[grid.slots]
        return out

    res.raw_scores = back(res.raw_scores, 0.0)
    res.scores = back(res.scores, 0.0)
    res.labels = back(res.labels, False)
    if res.column_scores is not None:
        res.column_scores = back(res.column_scores, 0.0)
    to_row = {int(s): int(r) for s, r in zip(grid.slots, grid.rows, strict=True)}
    kept = []
    for f in res.findings:
        if f.row in to_row:  # findings on inserted (empty) points are dropped
            f.row = to_row[f.row]
            kept.append(f)
    res.findings = kept
    return res


def _unsort(arr, order):
    out = arr.copy()
    out[order] = arr
    return out
