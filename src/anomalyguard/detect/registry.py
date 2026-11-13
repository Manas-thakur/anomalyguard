"""Name -> detector class registry and a spec-based factory."""

from __future__ import annotations

from typing import Any

from anomalyguard.detect.base import Detector
from anomalyguard.detect.contextual import GroupedDetector
from anomalyguard.detect.ensemble import EnsembleDetector
from anomalyguard.detect.ml import IsolationForestDetector, KNNDetector, LOFDetector
from anomalyguard.detect.statistical import GrubbsDetector, IQRDetector, MADDetector, ZScoreDetector
from anomalyguard.detect.timeseries import (
    CUSUMDetector,
    EWMADetector,
    FlatlineDetector,
    RollingZScoreDetector,
    SeasonalResidualDetector,
)

DETECTORS: dict[str, type[Detector]] = {
    "zscore": ZScoreDetector,
    "mad": MADDetector,
    "iqr": IQRDetector,
    "grubbs": GrubbsDetector,
    "iforest": IsolationForestDetector,
    "lof": LOFDetector,
    "knn": KNNDetector,
    "rolling_zscore": RollingZScoreDetector,
    "ewma": EWMADetector,
    "seasonal": SeasonalResidualDetector,
    "cusum": CUSUMDetector,
    "flatline": FlatlineDetector,
}

ALIASES = {
    "z": "zscore",
    "z_score": "zscore",
    "modified_zscore": "mad",
    "robust_zscore": "mad",
    "tukey": "iqr",
    "isolation_forest": "iforest",
    "isolationforest": "iforest",
    "local_outlier_factor": "lof",
    "knn_distance": "knn",
    "rolling": "rolling_zscore",
    "moving_average": "rolling_zscore",
    "seasonal_decompose": "seasonal",
    "stl": "seasonal",
    "changepoint": "cusum",
    "change_point": "cusum",
    "flat_line": "flatline",
    "stuck": "flatline",
    "stuck_at": "flatline",
}

CATEGORIES = {
    "statistical": ["zscore", "mad", "iqr", "grubbs"],
    "ml": ["iforest", "lof", "knn"],
    "timeseries": ["rolling_zscore", "ewma", "seasonal", "cusum", "flatline"],
}


def canonical_name(name: str) -> str:
    key = name.strip().lower().replace("-", "_")
    key = ALIASES.get(key, key)
    if key not in DETECTORS:
        raise KeyError(f"Unknown detector '{name}'. Available: {', '.join(sorted(DETECTORS))}")
    return key


def build_detector(spec: str | dict[str, Any] | Detector) -> Detector:
    """Create a detector from a name or a spec mapping.

    Spec keys: ``method`` (or ``type``), ``columns``, ``threshold``,
    ``contamination``, ``params`` (constructor kwargs), ``group_by`` (wraps the
    detector in :class:`GroupedDetector`), ``min_group_size``.
    For ``method: ensemble`` give ``detectors: [...]`` and optional ``combine``.
    """
    if isinstance(spec, Detector):
        return spec
    if isinstance(spec, str):
        spec = {"method": spec}
    spec = dict(spec)
    method = str(spec.pop("method", spec.pop("type", ""))).lower()
    if not method:
        raise ValueError(f"Detector spec needs a 'method': {spec}")
    group_by = spec.pop("group_by", None)
    min_group_size = spec.pop("min_group_size", 20)
    params = dict(spec.pop("params", {}) or {})
    common = {k: spec.pop(k) for k in ("columns", "threshold", "contamination") if k in spec}
    params.update(spec)  # allow params inline, e.g. {method: iforest, n_estimators: 50}

    if method == "ensemble":
        raw_members = params.pop("detectors", None) or []
        if isinstance(raw_members, str):
            raw_members = [m.strip() for m in raw_members.split(",") if m.strip()]
        if not raw_members:
            raise ValueError(
                "ensemble needs member detectors: give 'detectors: [mad, iforest]' "
                "(CLI: --param ensemble.detectors=mad,iforest), or pass several detectors "
                "with combine=vote"
            )
        members = [build_detector(m) for m in raw_members]
        combine = params.pop("combine", params.pop("method_", "mean"))
        try:
            det: Detector = EnsembleDetector(members, method=combine, **params, **common)
        except TypeError as exc:
            raise ValueError(f"Invalid parameters for detector 'ensemble': {exc}") from exc
    else:
        cls = DETECTORS[canonical_name(method)]
        try:
            det = cls(**params, **common)
        except TypeError as exc:
            raise ValueError(f"Invalid parameters for detector '{method}': {exc}") from exc
    if group_by:
        det = GroupedDetector(det, group_by=group_by, min_group_size=min_group_size)
    return det


def describe_detectors() -> list[dict[str, str]]:
    out = []
    for cat, names in CATEGORIES.items():
        for n in names:
            cls = DETECTORS[n]
            out.append(
                {"name": n, "category": cat, "class": cls.__name__, "description": cls.description}
            )
    out.append(
        {
            "name": "grouped",
            "category": "contextual",
            "class": "GroupedDetector",
            "description": GroupedDetector.description,
        }
    )
    out.append(
        {
            "name": "ensemble",
            "category": "ensemble",
            "class": "EnsembleDetector",
            "description": EnsembleDetector.description,
        }
    )
    return out
