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

**Input files.** Commands that take a `path` read `.csv`, `.tsv`, `.json`, `.jsonl` / `.ndjson` and `.parquet` (Parquet needs the `parquet` extra), optionally compressed (`.gz`, `.bz2`, `.zip`, `.xz`). SQLite files (`.db`, `.sqlite`, `.sqlite3`) need `--table` (the error lists the tables). An empty file or one without data rows is an error.

**Data options.** `profile`, `validate`, `detect` and `fix` share these options for reading files (see [How CSV files are read](/anomalyguard/docs/concepts/sources/#how-csv-files-are-read)):

| Option | Default | Meaning |
|---|---|---|
| `--table` | | Table name for SQLite files |
| `--delimiter`, `--sep` | sniffed | CSV field delimiter (`'\t'` or `tab` for tabs) |
| `--encoding` | UTF-8, falling back to cp1252/latin-1 with a warning | File encoding (CSV, JSON) |
| `--na-values` | none | Extra CSV cell values to read as missing, comma-separated (e.g. `NA,N/A,null`). By default only empty cells are missing, so `NA` stays text |
| `--decimal` | `.` (`,` when detected in a semicolon file) | CSV decimal separator |

Warnings (a guessed encoding, gaps in a time series, a clamped `--min-votes`, the day/month order chosen for dates such as `03/04/2026`) are printed to stderr as `warning: ...`.

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
| [`findings`](#findings) | List a run's stored findings and their ids (for `feedback`) |
| [`detectors`](#detectors) | List the available detectors |

## profile

```
anomalyguard profile [--schema SCHEMA] [--schema-out SCHEMA_OUT] [data options] [--json] path
```

Infers a schema (or uses `--schema`), profiles every column (type, nulls, unique values, invalid values, statistics or top values) and computes completeness, validity, uniqueness, freshness and the quality score.

| Option | Default | Meaning |
|---|---|---|
| `--schema` | inferred | Validate against this schema instead of inferring one |
| `--schema-out` | | Write the inferred schema (`.yaml` or `.json`) |
| data options | | See **Data options** at the top of this page |
| `--json` | off | Print the full profile as JSON |

Exit code 0.

## validate

```
anomalyguard validate --schema SCHEMA [data options] [--max-errors MAX_ERRORS] [--json] path
```

Validates every row against a schema and prints the violations and the quality score.

| Option | Default | Meaning |
|---|---|---|
| `--schema` | required | Schema file (YAML or JSON) |
| data options | | See **Data options** at the top of this page |
| `--max-errors` | `20` | Violations to print (or include in `--json`) |
| `--json` | off | Print the validation report as JSON |

Exit code 0 when every rule passes, 1 when any rule fails.

## detect

```
anomalyguard detect [-m METHOD] [--columns COLUMNS] [--group-by GROUP_BY] [--time-column TIME_COLUMN]
                    [--param DETECTOR.KEY=VALUE] [--no-log-scale] [--db DB] [--no-tuned-thresholds]
                    [--combine {any,vote,all}] [--min-votes MIN_VOTES] [--contamination CONTAMINATION]
                    [--schema SCHEMA] [data options] [-o OUTPUT] [--top TOP] [--show-ids] [--json]
                    [--fail-on-anomalies] path
```

Runs detectors and prints a summary and the top rows with their reasons. Values are first coerced to their schema types (given or inferred), so stray strings do not hide numeric columns.

| Option | Default | Meaning |
|---|---|---|
| `-m`, `--method` | `mad,iforest` | Comma-separated detectors (see `anomalyguard detectors`; aliases such as `isolation_forest` work). An empty value is an error. `ensemble` needs `--param ensemble.detectors=...` |
| `--columns` | all numeric | Comma-separated columns to score |
| `--group-by` | | Detect within groups of these columns, comma-separated (contextual anomalies) |
| `--time-column` | | Sort by this column; time-series detectors run on a regular time grid (gaps become empty points, with a warning). A column that does not exist is an error |
| `--param` | | Detector parameter, repeatable: `seasonal.period=168`, `rolling_zscore.window=48`, `mad.threshold=5`, `ensemble.detectors=mad,iforest`, `ensemble.combine=vote`. Values are read as YAML |
| `--no-log-scale` | off | Score skewed positive columns on their original scale (statistical detectors use a log scale for them by default) |
| `--db` | `.anomalyguard/anomalyguard.db` | State database; thresholds tuned there with `feedback tune` are applied (and named on stderr) |
| `--no-tuned-thresholds` | off | Ignore tuned thresholds |
| `--combine` | `any` | `any`, `vote` or `all`: when a row counts as anomalous |
| `--min-votes` | `2` | Detectors that must agree with `--combine vote`. More than the number of detectors is clamped (with a warning); with one detector `vote` is the same as `any` |
| `--contamination` | | Flag this share of rows per detector instead of using fixed thresholds |
| `--schema` | inferred | Schema used to coerce types |
| data options | | See **Data options** at the top of this page |
| `-o`, `--output` | | Write the full JSON report here |
| `--top` | `10` | Rows to print (or include in `--json`) |
| `--show-ids` | off | Also list every finding (row position, index, column, detector, score) |
| `--json` | off | Print the report as JSON |
| `--fail-on-anomalies` | off | Exit with code 1 if anything is flagged |

## fix

```
anomalyguard fix -o OUTPUT [-m METHOD] [--columns COLUMNS] [--group-by GROUP_BY] [--time-column TIME_COLUMN]
                 [--param DETECTOR.KEY=VALUE] [--no-log-scale] [--db DB] [--no-tuned-thresholds]
                 [--schema SCHEMA] [data options] [--missing MISSING] [--missing-value VALUE]
                 [--outlier OUTLIER] [--min MIN] [--max MAX] [--invalid INVALID] [--no-dedupe]
                 [--flag-column FLAG_COLUMN] [--report REPORT] [--review-db REVIEW_DB] path
```

Detects anomalies, applies a remediation policy to every column and writes the cleaned data. See [Remediation](/anomalyguard/docs/concepts/remediation/).

| Option | Default | Meaning |
|---|---|---|
| `-o`, `--output` | required | Cleaned output (`.csv`, `.jsonl`, `.json`, `.parquet`) |
| `-m`, `--method` | `mad` | Comma-separated detectors |
| `--columns`, `--group-by`, `--time-column`, `--param`, `--no-log-scale`, `--db`, `--no-tuned-thresholds` | | As for `detect`. With `--group-by`, outliers are capped within each group |
| `--schema` | inferred | Schema for types, ranges, primary key and allowed values |
| data options | | See **Data options** at the top of this page |
| `--missing` | `auto` | `auto`, `mean`, `median`, `mode`, `ffill`, `bfill`, `interpolate`, `constant`, `drop`, `flag`, `keep`. Identifier columns are never filled, and numeric fills do not apply to text: those cells are flagged |
| `--missing-value` | | Fill value for `--missing constant` (required with it) |
| `--outlier` | `cap` | `cap`, `winsorize`, `clip`, `median`, `mean`, `null`, `flag`, `drop`, `keep` |
| `--min`, `--max` | | Range for `--outlier clip` (at least one is required with it) |
| `--invalid` | `coerce` | Type errors: `coerce`, `drop`, `flag`, `keep` |
| `--no-dedupe` | off | Keep duplicate rows |
| `--flag-column` | | Add a boolean column marking rows that need review |
| `--report` | | Write a remediation report (`.md` for Markdown, anything else for JSON) |
| `--review-db` | | Add flagged items to this review queue (SQLite file) |

Per-column policies need a pipeline or the Python API. A policy error (`--outlier clip` without `--min`/`--max`, `--missing constant` without `--missing-value`) exits with code 2.

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

Each result line names the pipeline's own run number and the global run id used by the web app and API, e.g. `[orders] run 3 (#17): 1000 rows, ...`; without monitoring (`monitor.enabled: false`) only the run number is shown. When an alert could not be delivered on some channel the line ends with `N alerts (M with failed deliveries)` and a warning names the channel and the reason.

An invalid pipeline file (YAML error, unknown key or detector, bad `schedule` value, ...) stops `run` before anything runs, with the file name and field in the message (exit code 1). Exit code 1 if any run failed. With `--schedule`, a pipeline without a schedule is an error (exit code 2): add `schedule.every` or pass `--every`.

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
| `-n`, `--rows` | 1000 (orders), 1440 (sensor), 2000 (tabular) | Number of rows (at least 1) |
| `--seed` | `42` | Random seed |
| `-o`, `--output` | `<dataset>.csv` | Data file (`.csv`, `.jsonl` or `.parquet`; other extensions are an error) |
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
anomalyguard review [--value VALUE] [--note NOTE] [--status {pending,approved,rejected,applied,all}] [--limit LIMIT] [--db DB]
                    {list,approve,reject} [id]
```

Works through the [review queue](/anomalyguard/docs/concepts/review-and-feedback/).

| Action | Meaning |
|---|---|
| `list` | Print items (id, status, pipeline, row, column, value, suggestion, reason) |
| `approve ID` | Approve an item: the value to use is `--value`, else the value already approved (approving again keeps it), else the suggestion, else the original value. Whole-row items (no column) have no cell value; approving records the decision and says so |
| `reject ID` | Reject an item: keep the original value |

| Option | Default | Meaning |
|---|---|---|
| `--value` | | Value to use when approving (parsed as JSON when possible, otherwise text) |
| `--note` | | Reviewer note |
| `--status` | `pending` | Filter for `list`: `pending`, `approved`, `rejected`, `applied` or `all` |
| `--limit` | `50` | Items to list |
| `--db` | `.anomalyguard/anomalyguard.db` | Review queue database |

`approve` and `reject` without an id exit with code 2; an unknown id exits with code 1. A `--db` path that does not exist is an error (exit code 1); `review` never creates a database.

## feedback

```
anomalyguard feedback [--anomaly-id ANOMALY_ID] [--detector DETECTOR] [--note NOTE] [--db DB] {fp,tp,stats,tune}
```

| Action | Meaning |
|---|---|
| `fp` | Record a false positive for `--anomaly-id` (a stored finding id: see [`findings`](#findings), the web app or the API) or for `--detector` |
| `tp` | Record a true positive, the same way |
| `stats` | Confirmed, false-positive, precision and current threshold multiplier per detector |
| `tune` | Adjust threshold multipliers from feedback received since the last tune (see [Tuning](/anomalyguard/docs/concepts/review-and-feedback/#tuning)) |

| Option | Default | Meaning |
|---|---|---|
| `--anomaly-id` | | Stored finding id |
| `--detector` | | Detector name, when not using `--anomaly-id`: a registry name or alias (`mad`, `tukey`), or a name a run recorded, such as `grouped(mad by region)`. Unknown names exit with code 2 |
| `--note` | | Note stored with the feedback |
| `--db` | `.anomalyguard/anomalyguard.db` | Metrics database |

`fp` / `tp` without `--anomaly-id` or `--detector` exit with code 2; an unknown `--anomaly-id` exits with code 1. A `--db` path that does not exist is an error (exit code 1).

## findings

```
anomalyguard findings [--column COLUMN] [--detector DETECTOR] [--limit LIMIT] [--json] [--db DB] [run_id]
```

Lists a run's stored findings, highest score first, with the ids `feedback --anomaly-id` takes:

```
Run #17 (orders, run 3): 41 stored findings, highest score first
id   row  column      detector                score  reason
---  ---  ----------  ----------------------  -----  ------
812  794  unit_price  grouped(mad by region)  94.47  [region=east] unit_price=3035 has modified z-score ...
```

| Option | Default | Meaning |
|---|---|---|
| `run_id` | latest pipeline run | Global run id (as shown by `run` and the web app) |
| `--column`, `--detector` | | Only these findings |
| `--limit` | `50` | Findings to print |
| `--json` | off | Print `{"run_id", "total", "findings"}` as JSON |
| `--db` | `.anomalyguard/anomalyguard.db` | Metrics database (must exist) |

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
