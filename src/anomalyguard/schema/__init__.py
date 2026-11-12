"""Schema registry, validation, type coercion and data-quality metrics."""

from anomalyguard.schema.coercion import CoercionResult, TypeCoercer, coerce_frame, coerce_series
from anomalyguard.schema.quality import QualityMetrics, compute_quality
from anomalyguard.schema.registry import DataType, Field, Schema, SchemaRegistry
from anomalyguard.schema.validator import FieldError, SchemaValidator, ValidationReport

__all__ = [
    "CoercionResult",
    "DataType",
    "Field",
    "FieldError",
    "QualityMetrics",
    "Schema",
    "SchemaRegistry",
    "SchemaValidator",
    "TypeCoercer",
    "ValidationReport",
    "coerce_frame",
    "coerce_series",
    "compute_quality",
]
