---
title: Pipelines
description: Declarative YAML pipelines, how a run works, where state goes, and how to schedule runs.
---

A **pipeline** is one YAML file that describes a whole check: where the data comes from, the schema, the detectors, the remediation policy, alerts, where to write the outputs and how often to run. The [Pipeline YAML reference](/anomalyguard/docs/reference/pipeline-yaml/) lists every key.

## Creating one

```bash
anomalyguard init --list                                    # csv_quality, timeseries_monitor, database_quality
anomalyguard init --source data/orders.csv --name orders    # writes pipeline.yaml from csv_quality
anomalyguard init -t timeseries_monitor --source data/sensor.csv --value-column temperature -o sensor.yaml
anomalyguard init -t database_quality --source data/app.db --table events --cursor id -o events.yaml
```

| Template | Source | Detectors | Remediation | Schedule |
|---|---|---|---|---|
| `csv_quality` | CSV file; schema inferred and saved on the first run | `mad`, `iforest` (and `mad` per group with `--group-by`) | dedupe, auto-impute, cap, coerce | every 1h |
| `timeseries_monitor` | CSV with a `timestamp` column | `seasonal` and `cusum` (period 24), `rolling_zscore` (window 6) on `--value-column` | interpolate missing, flag outliers | every 5m |
| `database_quality` | SQL table with an incremental `--cursor` | `iqr`, `iforest` | off (report only) | every 15m |

In the web app, **Pipelines → New pipeline** does the same, optionally pointing at an uploaded file.

## What a run does

1. Read the source (only new rows when `state.incremental` is on). An empty read ends the run with status `empty`. Incremental runs keep a reference window of earlier rows (`detection.reference_rows`, default 5,000): detectors are fitted on those rows plus the new batch, and only the new rows are reported, so a batch of three rows is judged against history rather than against itself. A batch under 30 rows with no reference rows (the first run, or `reference_rows: 0`) gives a warning.
2. Load or infer the schema, validate and coerce, compute the quality score.
3. Run the detectors on the coerced data, applying feedback threshold multipliers.
4. Remediate according to the policy, and queue flagged values for review.
5. Evaluate alert rules against the run metrics (with the previous run for `change` rules) and notify.
6. Store the run, its metrics and its top findings (`monitor.store_anomalies`, default 1,000) in the monitor database; tune thresholds if `monitor.auto_tune` is on.
7. Write the sink: cleaned data, the anomalies JSON and the remediation report.

If any step raises an error, the run is recorded as `failed` with the error, and a `critical` alert is sent. `anomalyguard run` exits with code 1 when any pipeline failed.

## Paths and state

- `source.path`, `schema.path`, `sink.*path`, file notifier paths and explicit `monitor.db` / `review.db` / `state.dir` are resolved **relative to the YAML file**.
- `${VAR}` and `${VAR:-default}` are replaced with environment variables when the file is loaded.
- Runtime state defaults to **`.anomalyguard/` in the current working directory**: `anomalyguard.db` (runs, findings, alerts, feedback, thresholds, review queue, jobs) and `state/` (checkpoints, run counters, alert rate-limit history). That is where `anomalyguard serve` looks by default, so run both from the same folder.

When the web app runs a pipeline, it records into the server's database and state folder unless the pipeline sets `monitor.db` or `state.dir` itself.

## Running and scheduling

```bash
anomalyguard run pipeline.yaml                         # once
anomalyguard run a.yaml b.yaml --json                  # several, JSON results
anomalyguard run pipeline.yaml --schedule              # repeat on schedule.every / schedule.interval_seconds
anomalyguard run pipeline.yaml --every 5m --max-runs 12
```

The scheduler runs pipelines one at a time in one process. Runs never overlap: if a run takes longer than its interval, the next starts right after it. Ctrl+C stops it. Durations are `30s`, `5m`, `2h`, `1d` or plain seconds; cron expressions are not supported.

For an always-on schedule, run `anomalyguard run --schedule` under a process supervisor (systemd, a container with a restart policy) or call `anomalyguard run` from cron. The web app runs pipelines on demand as background jobs.

## The web app

The **Pipelines** page lists YAML files from the pipeline folders (`pipelines/` and `examples/` under the working directory by default; set `ANOMALYGUARD_PIPELINE_DIRS` or `serve --pipeline-dir`). You can edit and validate the YAML, run a pipeline now, and create new ones from templates. New pipelines are written to the first folder. See the [Web app guide](/anomalyguard/docs/guides/web-app/#pipelines).

## In Python

```python
from anomalyguard.pipeline import PipelineConfig, run_pipeline

cfg = PipelineConfig.load("pipeline.yaml")
result = run_pipeline(cfg, console=False)
print(result.status, result.run_id, result.metrics["anomaly_rate"], result.outputs)
```
