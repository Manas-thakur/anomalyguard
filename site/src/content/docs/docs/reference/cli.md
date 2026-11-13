---
title: CLI reference
description: Every anomalyguard command, subcommand and flag, with defaults and exit codes.
---

```
anomalyguard [-h] [--version] [-v] command ...
```

| Global option | Meaning |
|---|---|
| `-h`, `--help` | Show help (also on every command) |
| `--version` | Print `anomalyguard 0.3.0` and exit |
| `-v`, `--verbose` | Debug logging and full tracebacks |

`python -m anomalyguard` is equivalent to `anomalyguard`.

**Input files.** Commands that take a `path` read `.csv`, `.tsv`, `.json`, `.jsonl` / `.ndjson` and `.parquet` (Parquet needs the `parquet` extra), optionally compressed (`.gz`, `.bz2`, `.zip`, `.xz`). SQLite files (`.db`, `.sqlite`, `.sqlite3`) need `--table`.

**State.** Commands with `--db` default to `.anomalyguard/anomalyguard.db` in the current directory.

| Command | What it does |
|---|---|
| [`profile`](#profile) | Profile a dataset: types, stats, quality score |
| [`validate`](#validate) | Validate a dataset against a schema file |
| [`detect`](#detect) | Detect anomalies and explain them |
| [`fix`](#fix) | Detect and remediate, writing a cleaned file |
| [`run`](#run) | Run pipeline YAML file(s) |
| [`init`](#init) | Write a starter pipeline.yaml |
| [`demo`](#demo) | Synthetic data and benchmarks |
| [`serve`](#serve) | Start the web app and REST API (needs `anomalyguard[server]`) |
| [`doctor`](#doctor) | Check the environment, state, extras and notifiers |
| [`review`](#review) | List, approve or reject flagged values |
| [`feedback`](#feedback) | Mark anomalies as false or true positives and tune thresholds |
| [`detectors`](#detectors) | List the available detectors |

## profile

```
anomalyguard profile [--schema SCHEMA] [--schema-out SCHEMA_OUT] [--table TABLE] [--json] path
```

Infers a schema (or uses `--schema`), profiles every column (type, nulls, unique values, invalid values, statistics or top values) and computes completeness, validity, uniqueness, freshness and the quality score.

| Option | Default | Meaning |
|---|---|---|
| `--schema` | inferred | Validate against this schema instead of inferring one |
| `--schema-out` | | Write the inferred schema (`.yaml` or `.json`) |
| `--table` | | Table name for SQLite files |
| `--json` | off | Print the full profile as JSON |

Exit code 0.

## validate

```
anomalyguard validate --schema SCHEMA [--table TABLE] [--max-errors MAX_ERRORS] [--json] path
```

Validates every row against a schema and prints the violations and the quality score.

| Option | Default | Meaning |
|---|---|---|
| `--schema` | required | Schema file (YAML or JSON) |
| `--table` | | Table name for SQLite files |
| `--max-errors` | `20` | Violations to print (or include in `--json`) |
| `--json` | off | Print the validation report as JSON |

Exit code 0 when every rule passes, 1 when any rule fails.

## detect

```
anomalyguard detect [-m METHOD] [--columns COLUMNS] [--group-by GROUP_BY] [--time-column TIME_COLUMN]
                    [--combine {any,vote,all}] [--min-votes MIN_VOTES] [--contamination CONTAMINATION]
                    [--schema SCHEMA] [--table TABLE] [-o OUTPUT] [--top TOP] [--json] [--fail-on-anomalies]
                    path
```

Runs detectors and prints a summary and the top rows with their reasons. Values are first coerced to their schema types (given or inferred), so stray strings do not hide numeric columns.

| Option | Default | Meaning |
|---|---|---|
| `-m`, `--method` | `mad,iforest` | Comma-separated detectors (see `anomalyguard detectors`; aliases such as `isolation_forest` work) |
| `--columns` | all numeric | Comma-separated columns to score |
| `--group-by` | | Detect within groups of this column (contextual anomalies) |
| `--time-column` | | Sort by this column first (time-series detectors) |
| `--combine` | `any` | `any`, `vote` or `all`: when a row counts as anomalous |
| `--min-votes` | `2` | Detectors that must agree with `--combine vote` |
| `--contamination` | | Flag this share of rows per detector instead of using fixed thresholds |
| `--schema` | inferred | Schema used to coerce types |
| `--table` | | Table name for SQLite files |
| `-o`, `--output` | | Write the full JSON report here |
| `--top` | `10` | Rows to print (or include in `--json`) |
| `--json` | off | Print the report as JSON |
| `--fail-on-anomalies` | off | Exit with code 1 if anything is flagged |

## fix

```
anomalyguard fix -o OUTPUT [-m METHOD] [--columns COLUMNS] [--group-by GROUP_BY] [--time-column TIME_COLUMN]
                 [--schema SCHEMA] [--table TABLE] [--missing MISSING] [--outlier OUTLIER] [--invalid INVALID]
                 [--no-dedupe] [--flag-column FLAG_COLUMN] [--report REPORT] [--review-db REVIEW_DB]
                 path
```

Detects anomalies, applies a remediation policy to every column and writes the cleaned data. See [Remediation](/anomalyguard/docs/concepts/remediation/).

| Option | Default | Meaning |
|---|---|---|
| `-o`, `--output` | required | Cleaned output (`.csv`, `.jsonl`, `.json`, `.parquet`) |
| `-m`, `--method` | `mad` | Comma-separated detectors |
| `--columns`, `--group-by`, `--time-column` | | As for `detect` |
| `--schema` | inferred | Schema for types, ranges, primary key and allowed values |
| `--table` | | Table name for SQLite files |
| `--missing` | `auto` | `auto`, `mean`, `median`, `mode`, `ffill`, `bfill`, `interpolate`, `drop`, `flag`, `keep` |
| `--outlier` | `cap` | `cap`, `winsorize`, `median`, `mean`, `null`, `flag`, `drop`, `keep` |
| `--invalid` | `coerce` | Type errors: `coerce`, `drop`, `flag`, `keep` |
| `--no-dedupe` | off | Keep duplicate rows |
| `--flag-column` | | Add a boolean column marking rows that need review |
| `--report` | | Write a remediation report (`.md` for Markdown, anything else for JSON) |
| `--review-db` | | Add flagged items to this review queue (SQLite file) |

Per-column policies, `clip` and `constant` need a pipeline or the Python API.

## run

```
anomalyguard run [--schedule] [--every EVERY] [--max-runs MAX_RUNS] [--json] pipelines [pipelines ...]
```

Runs one or more [pipelines](/anomalyguard/docs/concepts/pipelines/) once, or repeatedly.

| Option | Default | Meaning |
|---|---|---|
| `--schedule` | off | Keep running on each pipeline's `schedule` |
| `--every` | | Run repeatedly at this interval (`30s`, `5m`, `1h`, `1d`), overriding the schedule |
| `--max-runs` | unlimited | Stop after N runs per pipeline |
| `--json` | off | Print each result as JSON (without the default console notifier) |

Exit code 1 if any run failed. With `--schedule`, a pipeline without a schedule is an error (exit code 2): add `schedule.every` or pass `--every`.

## init

```
anomalyguard init [-t TEMPLATE] [-o OUTPUT] [--name NAME] [--source SOURCE] [--group-by GROUP_BY]
                  [--value-column VALUE_COLUMN] [--table TABLE] [--cursor CURSOR] [--force] [--list]
```

| Option | Default | Meaning |
|---|---|---|
| `-t`, `--template` | `csv_quality` | `csv_quality`, `timeseries_monitor` or `database_quality` |
| `-o`, `--output` | `pipeline.yaml` | File to write |
| `--name` | source file name, else `my_pipeline` | Pipeline name |
| `--source` | `data.csv` (`data.db` for `database_quality`) | Data file or database, written into the YAML as given (paths in the YAML are relative to the YAML file) |
| `--group-by` | | (`csv_quality`) add a per-group `mad` detector |
| `--value-column` | `value` | (`timeseries_monitor`) column to monitor |
| `--table` | `events` | (`database_quality`) table name |
| `--cursor` | `id` | (`database_quality`) incremental cursor column |
| `--force` | off | Overwrite an existing file (otherwise exit code 1) |
| `--list` | | List the templates and exit |

## demo

### demo generate

```
anomalyguard demo generate [-d {orders,sensor,tabular}] [-n ROWS] [--seed SEED] [-o OUTPUT] [--labels LABELS]
```

Writes a synthetic dataset with labelled anomalies and a ground-truth file.

| Option | Default | Meaning |
|---|---|---|
| `-d`, `--dataset` | `orders` | `orders` (region-dependent prices, point and contextual anomalies, missing values, type errors, duplicates), `sensor` (hourly series with a daily cycle: point, contextual, collective and drift anomalies), `tabular` (correlated 6-D Gaussian with point and correlation anomalies) |
| `-n`, `--rows` | 1000 (orders), 1440 (sensor), 2000 (tabular) | Number of rows |
| `--seed` | `42` | Random seed |
| `-o`, `--output` | `<dataset>.csv` | Data file (`.csv`, `.jsonl`, `.json`, `.parquet`) |
| `--labels` | `<output>_labels.csv` | Ground-truth file (`is_anomaly`, `anomaly_type`, `column`) |

### demo benchmark

```
anomalyguard demo benchmark [--datasets DATASETS] [--seed SEED] [-o OUTPUT] [--json]
```

Precision, recall, F1 and ROC-AUC of every detector on the synthetic datasets, at each detector's default threshold. See [Benchmarks](/anomalyguard/docs/benchmarks/).

| Option | Default | Meaning |
|---|---|---|
| `--datasets` | `tabular,orders,sensor` | Comma-separated datasets |
| `--seed` | `42` | Random seed |
| `-o`, `--output` | | Also write the results (`.json` for JSON, anything else for Markdown) |
| `--json` | off | Print JSON instead of Markdown tables |

## serve

```
anomalyguard serve [--db DB] [--host HOST] [--port PORT] [--pipeline-dir PIPELINE_DIR] [--max-upload-mb MAX_UPLOAD_MB]
```

Starts the [web app](/anomalyguard/docs/guides/web-app/) and the [HTTP API](/anomalyguard/docs/reference/http-api/). Needs the `server` extra; without it, prints how to install it and exits with code 1.

| Option | Default | Meaning |
|---|---|---|
| `--db` | `.anomalyguard/anomalyguard.db` | Metrics database; uploads and analyses go next to it |
| `--host` | `127.0.0.1` | Interface to listen on |
| `--port` | `8765` | Port |
| `--pipeline-dir` | `pipelines`, `examples` (or `ANOMALYGUARD_PIPELINE_DIRS`) | Folder with pipeline YAML files; repeatable. The first receives pipelines created in the UI |
| `--max-upload-mb` | `100` (or `ANOMALYGUARD_MAX_UPLOAD_MB`) | Upload size limit |

Other server settings come from [environment variables](/anomalyguard/docs/reference/configuration/). `serve` warns when it listens on a non-local address without `ANOMALYGUARD_API_KEY`.

## doctor

```
anomalyguard doctor [--db DB] [--pipeline-dir PIPELINE_DIR] [--json]
```

Checks the state directory (writable?), the database (runs, pending reviews, uploads), the optional extras, environment variables (secret values are never printed), pipeline files (valid?) and each pipeline's notifiers (secrets available?), then lists the problems found.

| Option | Default | Meaning |
|---|---|---|
| `--db` | `.anomalyguard/anomalyguard.db` | Database to inspect |
| `--pipeline-dir` | `ANOMALYGUARD_PIPELINE_DIRS`, else `pipelines`, `examples` | Folder with pipeline YAML files; repeatable |
| `--json` | off | Print everything (plus a `problems` list) as JSON |

Exit code 1 only when the state directory is not writable; other problems are reported but exit 0.

## review

```
anomalyguard review [--value VALUE] [--note NOTE] [--status {pending,approved,rejected,all}] [--limit LIMIT] [--db DB]
                    {list,approve,reject} [id]
```

Works through the [review queue](/anomalyguard/docs/concepts/review-and-feedback/).

| Action | Meaning |
|---|---|
| `list` | Print items (id, status, pipeline, row, column, value, suggestion, reason) |
| `approve ID` | Approve an item: the value to use is `--value`, else the suggestion, else the original value |
| `reject ID` | Reject an item: keep the original value |

| Option | Default | Meaning |
|---|---|---|
| `--value` | | Value to use when approving (parsed as JSON when possible, otherwise text) |
| `--note` | | Reviewer note |
| `--status` | `pending` | Filter for `list`: `pending`, `approved`, `rejected` or `all` |
| `--limit` | `50` | Items to list |
| `--db` | `.anomalyguard/anomalyguard.db` | Review queue database |

`approve` and `reject` without an id exit with code 2; an unknown id exits with code 1.

## feedback

```
anomalyguard feedback [--anomaly-id ANOMALY_ID] [--detector DETECTOR] [--note NOTE] [--db DB] {fp,tp,stats,tune}
```

| Action | Meaning |
|---|---|
| `fp` | Record a false positive for `--anomaly-id` (a stored finding id, shown in the web app and API) or for `--detector` |
| `tp` | Record a true positive, the same way |
| `stats` | Confirmed, false-positive, precision and current threshold multiplier per detector |
| `tune` | Adjust threshold multipliers from feedback received since the last tune (see [Tuning](/anomalyguard/docs/concepts/review-and-feedback/#tuning)) |

| Option | Default | Meaning |
|---|---|---|
| `--anomaly-id` | | Stored finding id |
| `--detector` | | Detector name, when not using `--anomaly-id` |
| `--note` | | Note stored with the feedback |
| `--db` | `.anomalyguard/anomalyguard.db` | Metrics database |

`fp` / `tp` without `--anomaly-id` or `--detector` exit with code 2.

## detectors

```
anomalyguard detectors
```

Lists every detector with its category and description:

```
name            category     description
--------------  -----------  ----------------------------------------------------------------------------
zscore          statistical  Distance from the mean in standard deviations (assumes roughly normal data).
mad             statistical  Modified z-score using median and median absolute deviation (robust).
iqr             statistical  Tukey fences: outside Q1 - k*IQR or Q3 + k*IQR (k=1.5).
grubbs          statistical  Iterative Grubbs test for outliers in normally distributed data.
iforest         ml           Isolation Forest: anomalies are isolated by fewer random splits.
lof             ml           Local Outlier Factor: density relative to neighbours (local outliers).
knn             ml           Mean distance to the k nearest neighbours (global outliers).
rolling_zscore  timeseries   Deviation from a trailing rolling window (median/IQR or mean/std).
ewma            timeseries   Residual from an exponentially weighted moving average forecast.
seasonal        timeseries   Robust z-score of residuals after removing trend and seasonality.
cusum           timeseries   CUSUM change-point detection for sustained level shifts and drift.
grouped         contextual   Runs a base detector separately within each group (contextual anomalies).
ensemble        ensemble     Combines detectors by score averaging or majority vote.
```

See the [Detector reference](/anomalyguard/docs/reference/detectors/) for parameters.
