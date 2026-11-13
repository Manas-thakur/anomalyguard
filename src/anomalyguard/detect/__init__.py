"""Anomaly detectors (statistical, ML, time-series, contextual, ensemble)."""

from anomalyguard.detect.base import (
    DetectionResult,
    Detector,
    Finding,
    NotFittedError,
    numeric_columns,
    to_matrix,
)
from anomalyguard.detect.contextual import GroupedDetector
from anomalyguard.detect.ensemble import EnsembleDetector
from anomalyguard.detect.evaluation import evaluate, precision_recall_f1, roc_auc
from anomalyguard.detect.ml import IsolationForestDetector, KNNDetector, LOFDetector
from anomalyguard.detect.registry import (
    DETECTORS,
    build_detector,
    canonical_name,
    describe_detectors,
)
from anomalyguard.detect.report import AnomalyReport
from anomalyguard.detect.runner import DEFAULT_METHODS, run_detectors
from anomalyguard.detect.statistical import GrubbsDetector, IQRDetector, MADDetector, ZScoreDetector
from anomalyguard.detect.timeseries import (
    CUSUMDetector,
    EWMADetector,
    FlatlineDetector,
    RollingZScoreDetector,
    SeasonalResidualDetector,
)

__all__ = [
    "DEFAULT_METHODS",
    "DETECTORS",
    "AnomalyReport",
    "CUSUMDetector",
    "DetectionResult",
    "Detector",
    "EWMADetector",
    "EnsembleDetector",
    "Finding",
    "FlatlineDetector",
    "GroupedDetector",
    "GrubbsDetector",
    "IQRDetector",
    "IsolationForestDetector",
    "KNNDetector",
    "LOFDetector",
    "MADDetector",
    "NotFittedError",
    "RollingZScoreDetector",
    "SeasonalResidualDetector",
    "ZScoreDetector",
    "build_detector",
    "canonical_name",
    "describe_detectors",
    "evaluate",
    "numeric_columns",
    "precision_recall_f1",
    "roc_auc",
    "run_detectors",
    "to_matrix",
]
