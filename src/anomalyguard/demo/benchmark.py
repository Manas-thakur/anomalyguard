"""Benchmark detectors against the synthetic datasets with known labels."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from anomalyguard.demo.generator import generate_orders, generate_sensor, generate_tabular
from anomalyguard.detect.evaluation import evaluate
from anomalyguard.detect.registry import build_detector
from anomalyguard.ingest.inference import infer_schema
from anomalyguard.schema.validator import SchemaValidator

# Which anomaly types each dataset's detector benchmark counts as positives.
# Missing values, type errors and duplicates are data-quality issues caught by
# schema validation (benchmarked separately), not by outlier detectors.
DETECTOR_TYPES = {
    "tabular": {"point", "correlation"},
    "orders": {"point", "contextual"},
    "sensor": {"point", "contextual", "collective", "drift"},
}

DEFAULT_SUITE: dict[str, list[dict[str, Any]]] = {
    "tabular": [
        {"method": "zscore"},
        {"method": "mad"},
        {"method": "iqr"},
        {"method": "grubbs"},
        {"method": "iforest"},
        {"method": "lof"},
        {"method": "knn"},
        {
            "method": "ensemble",
            "detectors": ["mad", "lof", "knn"],
            "combine": "vote",
            "min_votes": 2,
        },
    ],
    "orders": [
        {"method": "zscore"},
        {"method": "mad"},
        {"method": "iqr"},
        {"method": "iforest"},
        {"method": "lof"},
        {"method": "mad", "group_by": "region"},
        {"method": "iqr", "group_by": "region"},
    ],
    "sensor": [
        {"method": "zscore", "columns": ["temperature"]},
        {"method": "mad", "columns": ["temperature"]},
        {"method": "rolling_zscore", "columns": ["temperature"], "window": 6},
        {"method": "ewma", "columns": ["temperature"], "span": 3},
        {"method": "seasonal", "columns": ["temperature"], "period": 24},
        {"method": "cusum", "columns": ["temperature"], "period": 24},
        {"method": "iforest", "columns": ["temperature"]},
        {
            "method": "ensemble",
            "detectors": [{"method": "seasonal", "period": 24}, {"method": "cusum", "period": 24}],
            "combine": "max",
        },
    ],
}

ORDER_COLUMNS = ["quantity", "unit_price", "delivery_days"]


_LABEL_PARAMS = ("window", "span", "period", "k", "n_neighbors")


def _spec_label(spec: dict[str, Any]) -> str:
    s = dict(spec)
    name = s.pop("method")
    if name == "ensemble":
        return f"ensemble[{s.get('combine', 'mean')}]({'+'.join(s.get('detectors', []))})"
    params = ", ".join(f"{k}={s[k]}" for k in _LABEL_PARAMS if k in s)
    label = f"{name}({params})" if params else name
    if "group_by" in s:
        label += f" by {s['group_by']}"
    return label


@dataclass
class BenchmarkResult:
    dataset: str
    detector: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    tp: int
    fp: int
    fn: int
    n_rows: int
    n_positive: int
    seconds: float
    recall_by_type: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    results: list[BenchmarkResult]
    quality: list[dict[str, Any]]
    seed: int

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.to_dict() for r in self.results])

    def best(self) -> dict[str, str]:
        out = {}
        for ds in dict.fromkeys(r.dataset for r in self.results):
            rs = [r for r in self.results if r.dataset == ds]
            out[ds] = max(rs, key=lambda r: r.f1).detector
        return out

    def to_markdown(self) -> str:
        lines = [
            f"Seed {self.seed}. Precision/recall/F1 at each detector's default threshold; ROC-AUC from raw scores.",
            "",
        ]
        for ds in dict.fromkeys(r.dataset for r in self.results):
            rs = [r for r in self.results if r.dataset == ds]
            types = sorted({t for r in rs for t in r.recall_by_type})
            lines.append(f"### {ds} ({rs[0].n_rows} rows, {rs[0].n_positive} anomalies)")
            lines.append("")
            header = (
                "| Detector | Precision | Recall | F1 | ROC-AUC | "
                + " | ".join(f"Recall: {t}" for t in types)
                + " | Time (s) |"
            )
            lines.append(header)
            lines.append("|" + "---|" * (6 + len(types)))
            for r in rs:
                per = " | ".join(f"{r.recall_by_type.get(t, 0):.2f}" for t in types)
                lines.append(
                    f"| {r.detector} | {r.precision:.2f} | {r.recall:.2f} | {r.f1:.2f} | {r.roc_auc:.3f} | {per} | {r.seconds:.2f} |"
                )
            lines.append("")
        if self.quality:
            lines.append("### Data-quality checks (schema validation on `orders`)")
            lines.append("")
            lines.append("| Issue | Injected | Caught | Recall |")
            lines.append("|---|---|---|---|")
            for q in self.quality:
                lines.append(
                    f"| {q['type']} | {q['injected']} | {q['caught']} | {q['recall']:.2f} |"
                )
            lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "results": [r.to_dict() for r in self.results],
            "quality": self.quality,
        }


def _score_detector(
    df: pd.DataFrame,
    labels: pd.DataFrame,
    spec: dict[str, Any],
    positives: set[str],
    dataset: str,
    columns: list[str] | None,
) -> BenchmarkResult:
    spec = dict(spec)
    if columns and "columns" not in spec and spec["method"] != "ensemble":
        spec["columns"] = columns
    if spec["method"] == "ensemble" and columns:
        spec["detectors"] = [
            {**({"method": m} if isinstance(m, str) else m), "columns": columns}
            for m in spec["detectors"]
        ]
    label = _spec_label(
        {
            **spec,
            "detectors": [
                d["method"] if isinstance(d, dict) else d for d in spec.get("detectors", [])
            ],
        }
    )
    y = labels["anomaly_type"].isin(positives).to_numpy()
    t0 = time.perf_counter()
    det = build_detector(spec)
    res = det.fit_detect(df)
    elapsed = time.perf_counter() - t0
    m = evaluate(y, res.labels, res.scores)
    per_type = {}
    for t in sorted(positives):
        mask = (labels["anomaly_type"] == t).to_numpy()
        if mask.any():
            per_type[t] = float(res.labels[mask].mean())
    return BenchmarkResult(
        dataset=dataset,
        detector=label,
        precision=m["precision"],
        recall=m["recall"],
        f1=m["f1"],
        roc_auc=m["roc_auc"],
        tp=m["tp"],
        fp=m["fp"],
        fn=m["fn"],
        n_rows=len(df),
        n_positive=int(y.sum()),
        seconds=elapsed,
        recall_by_type=per_type,
    )


def quality_check_recall(df: pd.DataFrame, labels: pd.DataFrame) -> list[dict[str, Any]]:
    """How many injected missing/type-error/duplicate rows schema validation catches.

    The schema is inferred from the data (as ``anomalyguard profile --schema-out``
    would produce, which makes ``order_id`` unique) and then every column is
    declared required - the same as ``examples/orders.schema.yaml``.
    """
    schema = infer_schema(df, name="orders")
    for fld in schema.fields.values():
        fld.nullable = False
    rep = SchemaValidator(schema).validate(df)
    rows_by_rule: dict[str, set[int]] = {}
    for e in rep.errors:
        rows_by_rule.setdefault(e.rule, set()).add(e.row)
    caught_rules = {
        "missing": {"not_null"},
        "type_error": {"type"},
        "duplicate": {"unique", "primary_key"},
    }
    out = []
    for t, rules in caught_rules.items():
        rows = set(np.flatnonzero((labels["anomaly_type"] == t).to_numpy()).tolist())
        caught_rows = set().union(*(rows_by_rule.get(r, set()) for r in rules))
        caught = len(rows & caught_rows)
        out.append(
            {
                "type": t,
                "injected": len(rows),
                "caught": caught,
                "recall": caught / len(rows) if rows else 0.0,
            }
        )
    return out


def run_benchmark(
    datasets: list[str] | None = None,
    seed: int = 42,
    rows: dict[str, int] | None = None,
    suite: dict[str, list[dict[str, Any]]] | None = None,
) -> BenchmarkReport:
    """Run every detector in ``suite`` on each dataset and compute metrics."""
    datasets = datasets or ["tabular", "orders", "sensor"]
    suite = suite or DEFAULT_SUITE
    rows = rows or {}
    results: list[BenchmarkResult] = []
    quality: list[dict[str, Any]] = []
    for ds in datasets:
        if ds == "tabular":
            df, labels = generate_tabular(n_rows=rows.get(ds, 2000), seed=seed)
            columns = None
        elif ds == "orders":
            df, labels = generate_orders(n_rows=rows.get(ds, 2000), seed=seed)
            columns = ORDER_COLUMNS
            quality = quality_check_recall(df, labels)
        elif ds == "sensor":
            df, labels = generate_sensor(n_points=rows.get(ds, 24 * 60), seed=seed)
            columns = ["temperature"]
        else:
            raise KeyError(f"Unknown benchmark dataset '{ds}'")
        for spec in suite[ds]:
            results.append(_score_detector(df, labels, spec, DETECTOR_TYPES[ds], ds, columns))
    return BenchmarkReport(results=results, quality=quality, seed=seed)
