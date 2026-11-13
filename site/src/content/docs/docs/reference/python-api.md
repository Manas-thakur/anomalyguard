---
title: Python API
description: anomalyguard.read, profile, detect and fix, the detector classes, RemediationPipeline, ReviewQueue, alerts and pipelines from Python.
---

Everything the CLI and the web app do is available as a library. The examples below run against `orders.csv` from `anomalyguard demo generate -d orders -o orders.csv`.

## Top-level functions

```python
import anomalyguard as ag

df = ag.read("orders.csv")             # CSV/TSV/JSON/JSONL/Parquet, or SQLite with table=
prof = ag.profile(df)                   # inferred schema, column profiles, quality, validation
report = ag.detect(df, ["mad", "iforest"], group_by="region")
result = ag.fix(df)                     # detect with mad, then the default remediation policy

print(ag.__version__)
print(prof.quality.score)               # 0.98625
print(report.n_anomalies, report.anomaly_rate)
print(len(result.data), result.n_changed_cells, len(result.flagged))
```

| Function | Signature | Returns |
|---|---|---|
| `read` | `read(path, **options)` | `pandas.DataFrame`. Options are source options, e.g. `table=` for SQLite, `limit=` |
| `profile` | `profile(data, schema=None, name="dataset")` | `Profile` with `schema`, `columns` (per-column profiles), `quality` (`QualityMetrics`), `validation` (`ValidationReport`), and `to_dict()` |
| `detect` | `detect(data, methods=None, schema=None, **kwargs)` | `AnomalyReport`. `methods` defaults to `["mad", "iforest"]`; values are coerced to the (given or inferred) schema types first. `kwargs` go to `run_detectors` |
| `fix` | `fix(data, methods=None, policy=None, schema=None, **detect_kwargs)` | `RemediationResult`. Detects with `methods` (default `["mad"]`) and remediates with `policy` (a dict or `RemediationPolicy`) |

`data` can be a DataFrame or a path.

## Detection

```python
from anomalyguard.detect import (
    GroupedDetector, IsolationForestDetector, MADDetector, build_detector, run_detectors,
)

cols = ["quantity", "unit_price", "delivery_days"]
report = run_detectors(
    df,
    [
        MADDetector(columns=cols),
        GroupedDetector(MADDetector(columns=["unit_price"]), group_by="region"),
        IsolationForestDetector(columns=cols, n_estimators=200),
        {"method": "seasonal", "columns": ["unit_price"], "period": 24},   # specs work too
    ],
    combine="any",
)
for rec in report.records(limit=3):
    print(rec["index"], round(rec["score"], 2), rec["reasons"][0])
```

`run_detectors(df, methods=None, columns=None, group_by=None, time_column=None, combine="any", min_votes=1, threshold_multipliers=None, threshold_scale=1.0)` fits each detector on `df` and returns an `AnomalyReport`. `methods` may be names (or a comma-separated string), spec dicts or `Detector` instances; `columns` and `group_by` apply to specs that do not set them. With `time_column` the frame is sorted first and results are mapped back. `threshold_multipliers` maps detector names to multipliers; `threshold_scale` multiplies every threshold.

**`AnomalyReport`**: `n_rows`, `n_anomalies`, `anomaly_rate`, `anomalous_rows`, `findings` (list of `Finding`), `results` (one `DetectionResult` per detector), `votes`, `row_scores`, `counts_by_detector()`, `counts_by_column()`, `records(limit=None)` (rows with score, votes, columns and reasons, highest score first), `summary()`, `to_dict()`, `to_frame()`, `to_json(path=None)`.

**`Finding`**: `row` (position), `index` (original index label), `detector`, `column`, `value`, `score` (normalised; above 1 is anomalous), `reason`, `to_dict()`.

**Detectors** all have `fit(df)`, `score(df)`, `normalized_score(df)`, `predict(df)` (boolean labels), `detect(df)` (`DetectionResult` with `labels`, `scores`, `raw_scores`, `threshold`, `columns`, `findings`) and `fit_detect(df)`. Classes: `ZScoreDetector`, `MADDetector`, `IQRDetector`, `GrubbsDetector`, `IsolationForestDetector`, `LOFDetector`, `KNNDetector`, `RollingZScoreDetector`, `EWMADetector`, `SeasonalResidualDetector`, `CUSUMDetector`, `GroupedDetector`, `EnsembleDetector`. `build_detector(spec)` builds one from a name or spec; `describe_detectors()` lists them; `DETECTORS` maps names to classes. Parameters are in the [Detector reference](/anomalyguard/docs/reference/detectors/).

`evaluate(y_true, y_pred, scores=None)`, `precision_recall_f1` and `roc_auc` in `anomalyguard.detect` score results against ground truth, as the benchmark does.

## Schema and quality

```python
from anomalyguard.schema import Schema, SchemaValidator, compute_quality
from anomalyguard.ingest import infer_schema

schema = infer_schema(df, name="orders")
schema.save("orders.schema.yaml")
schema = Schema.load("orders.schema.yaml")

validation = SchemaValidator(schema).validate(df)
print(validation.passed, validation.n_invalid_rows, validation.counts_by_rule())
quality = compute_quality(df, schema, validation)
print(quality.score, quality.completeness, quality.validity, quality.uniqueness)
```

See [Schema and quality score](/anomalyguard/docs/concepts/schema-and-quality/).

## Remediation

```python
from anomalyguard.remediate import RemediationPipeline

policy = {
    "default": {"missing": "auto", "outlier": "cap"},
    "columns": {"unit_price": {"outlier": "flag"}},
}
result = RemediationPipeline(policy, schema=schema).run(df, report)

result.data.to_csv("clean.csv", index=False)
summary = result.report().summary()
print(summary["cells_changed"], summary["rows_dropped"], summary["rows_flagged_for_review"])
markdown = result.report().to_markdown()
```

`RemediationPipeline(policy=None, schema=None, llm=None, llm_auto_apply=False, llm_min_confidence=0.8, llm_max_items=20)`. `run(df, report=None)` returns a `RemediationResult` with `data`, `original`, `changes` (each with `row`, `column`, `before`, `after`, `strategy`, `reason`), `dropped` (`{row: reason}`), `flagged` (`FlaggedItem` list), `n_changed_cells` and `report()` (`RemediationReport` with `summary()`, `to_markdown()`, `to_json()`). See [Remediation](/anomalyguard/docs/concepts/remediation/).

## Review queue

```python
from anomalyguard.remediate import ReviewQueue

queue = ReviewQueue("review.db")                        # any SQLite file; created if missing
ids = queue.add_flagged(result.flagged, pipeline="orders")
print(queue.counts())                                   # {'pending': ..., 'approved': 0, ...}

item = queue.list(status="pending", limit=1)[0]
queue.approve(item["id"], value=42, note="checked")     # or queue.reject(item["id"])
fixed, n = queue.apply(result.data, pipeline="orders", mark=True)
```

| Method | Meaning |
|---|---|
| `add_flagged(flagged, pipeline=None, run_id=None)` | Queue `FlaggedItem`s or dicts; already-pending duplicates are reused. Returns ids |
| `add(column, value, reason, row_index=None, pipeline=None, run_id=None, suggestion=None, ...)` | Queue one item |
| `list(status="pending", limit=..., pipeline=None)` | Items as dicts (`id`, `status`, `pipeline`, `run_id`, `row_index`, `column`, `value`, `reason`, `suggestion`, `resolved_value`, ...) |
| `query(...)` / `ids(...)` / `facets(status)` | Filtered, paged queries (as the web app uses) |
| `get(id)` / `counts()` | One item / counts per status |
| `approve(id, value=None, note=None)` | Value to use: `value`, else the suggestion, else the original |
| `reject(id, note=None)` | Keep the original value |
| `apply(df, pipeline=None, item_ids=None, mark=False)` | Write approved values into a copy of `df` (matched on index label and column). Returns `(df, n_written)`; `mark=True` sets them `applied` |

## Alerts

```python
from anomalyguard.alert import AlertManager, AlertRule, ConsoleNotifier, FileNotifier, RateLimiter

manager = AlertManager(
    notifiers=[ConsoleNotifier("info"), FileNotifier("alerts.jsonl")],
    rules=[AlertRule("anomaly_rate", ">", 0.03, "warning"), AlertRule("quality_score", "<", 0.95, "error")],
    rate_limiter=RateLimiter(max_per_window=20, window_seconds=3600, dedup_seconds=3600),
)
records = manager.process({"anomaly_rate": report.anomaly_rate, "quality_score": 0.98, "rows": len(df)}, source="orders")
print([(r.message.title, r.status) for r in records])
```

`AlertRule(metric, op=">", value=0.0, severity="warning", name=None, kind="threshold", message=None)`, or `AlertRule.from_dict({...})` with the YAML keys. Notifiers: `ConsoleNotifier`, `FileNotifier`, `WebhookNotifier`, `SlackNotifier`, `EmailNotifier`, and `create_notifier(dict)`. `AlertManager.evaluate(metrics)` returns messages, `dispatch(messages)` delivers them, and `process` does both. See [Alerts and notifiers](/anomalyguard/docs/guides/alerts/).

## Pipelines

```python
from anomalyguard.pipeline import PipelineConfig, PipelineExecutor, Scheduler, run_pipeline

cfg = PipelineConfig.load("pipeline.yaml")             # or PipelineConfig.from_yaml(text, base_dir=...)
result = run_pipeline(cfg, console=False)
print(result.status, result.run_id, result.metrics["quality_score"], result.outputs)

# every 5 minutes, three times
Scheduler([(cfg, 300)], max_runs=3).run()
```

`PipelineResult` has `name`, `status` (`success`, `failed` or `empty`), `run_id`, `metrics`, `alerts`, `outputs`, `error`, `report`, `remediation`, `quality`, `validation` and `to_dict()`. `PipelineConfig.load` raises `ConfigError` for invalid files.

## Sources

```python
from anomalyguard.ingest import CheckpointStore, IncrementalReader, StreamSource, create_source

src = create_source({"type": "csv", "path": "orders.csv", "cursor": "timestamp"})
reader = IncrementalReader(src, CheckpointStore("checkpoints.json"))   # a JSON file
new_rows = reader.read_new()          # everything the first time, only newer rows afterwards

stream = StreamSource(lambda: fetch_records(), name="events")   # re-invoked on every read
```

See [Sources](/anomalyguard/docs/concepts/sources/).

## Monitoring store and feedback

```python
from anomalyguard.monitor import FeedbackLoop, MetricsStore

store = MetricsStore(".anomalyguard/anomalyguard.db")
loop = FeedbackLoop(store)
print(loop.precision())          # per detector: true_positive, false_positive, n, precision
changes = loop.tune()            # ThresholdChange list
print(store.thresholds())        # {detector: multiplier}
```

To serve the web app from your own code, `anomalyguard.monitor.api.create_app(db_path, settings)` returns the FastAPI app (needs the `server` extra).
