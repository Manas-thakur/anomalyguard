"""Synthetic data with known anomalies and a detector benchmark."""

from anomalyguard.demo.benchmark import BenchmarkReport, BenchmarkResult, run_benchmark
from anomalyguard.demo.generator import (
    DATASETS,
    generate,
    generate_orders,
    generate_sensor,
    generate_tabular,
)

__all__ = [
    "DATASETS",
    "BenchmarkReport",
    "BenchmarkResult",
    "generate",
    "generate_orders",
    "generate_sensor",
    "generate_tabular",
    "run_benchmark",
]
