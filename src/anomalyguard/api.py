"""Convenience functions: ``read``, ``profile``, ``detect`` and ``fix``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from anomalyguard.detect.report import AnomalyReport
from anomalyguard.detect.runner import DEFAULT_METHODS, run_detectors
from anomalyguard.ingest.factory import read_any
from anomalyguard.ingest.inference import ColumnProfile, infer_schema
from anomalyguard.ingest.inference import profile as _profile_columns
from anomalyguard.remediate.pipeline import (
    RemediationPipeline,
    RemediationPolicy,
    RemediationResult,
)
from anomalyguard.schema.quality import QualityMetrics, compute_quality
from anomalyguard.schema.registry import Schema
from anomalyguard.schema.validator import SchemaValidator, ValidationReport


def read(path: str | Path, **options: Any) -> pd.DataFrame:
    """Read CSV/TSV/JSON/JSONL/Parquet (or SQLite with ``table=``) into a DataFrame."""
    return read_any(path, **options)


@dataclass
class Profile:
    schema: Schema
    columns: list[ColumnProfile]
    quality: QualityMetrics
    validation: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema.to_dict(),
            "columns": [c.to_dict() for c in self.columns],
            "quality": self.quality.to_dict(),
            "validation": self.validation.to_dict(max_errors=100),
        }


def _frame(data: pd.DataFrame | str | Path) -> pd.DataFrame:
    return data if isinstance(data, pd.DataFrame) else read_any(data)


def profile(
    data: pd.DataFrame | str | Path, schema: Schema | None = None, name: str = "dataset"
) -> Profile:
    """Infer (or use) a schema, profile every column and compute quality metrics."""
    df = _frame(data)
    schema = schema or infer_schema(df, name=name)
    validation = SchemaValidator(schema).validate(df)
    quality = compute_quality(df, schema, validation)
    return Profile(schema, _profile_columns(df, schema), quality, validation)


def detect(
    data: pd.DataFrame | str | Path,
    methods: list[Any] | str | None = None,
    schema: Schema | None = None,
    **kwargs: Any,
) -> AnomalyReport:
    """Run detectors (default ``mad`` + ``iforest``) and return an AnomalyReport.

    Values are first coerced to their (given or inferred) schema types, so a
    stray ``"unknown"`` in a numeric column does not hide the column.
    """
    df = _frame(data)
    schema = schema or infer_schema(df, infer_constraints=False)
    coerced = SchemaValidator(schema).validate(df).coerced
    report = run_detectors(
        coerced if coerced is not None else df, methods or list(DEFAULT_METHODS), **kwargs
    )
    report.index = list(df.index)
    return report


def fix(
    data: pd.DataFrame | str | Path,
    methods: list[Any] | str | None = None,
    policy: RemediationPolicy | dict[str, Any] | None = None,
    schema: Schema | None = None,
    **detect_kwargs: Any,
) -> RemediationResult:
    """Detect anomalies and remediate them according to ``policy``.

    Returns a :class:`RemediationResult`; ``result.data`` is the cleaned frame
    and ``result.report().to_markdown()`` explains every change.
    """
    df = _frame(data)
    schema = schema or infer_schema(df)
    report = detect(df, methods or ["mad"], schema=schema, **detect_kwargs)
    return RemediationPipeline(policy, schema=schema).run(df, report)
