---
title: Pipeline YAML reference
description: Every key of a pipeline file, with defaults.
---

A pipeline file is YAML with these top-level keys. `name` and `source` are required; unknown top-level keys are rejected. Validate a file with `anomalyguard doctor`, in the web app's pipeline editor, or with `POST /api/pipelines/validate`.

**Paths** (`source.path`, `schema.path`, `sink.*`, file notifier `path`, and explicit `monitor.db`, `review.db`, `state.dir`) are resolved relative to the YAML file. **Environment variables**: `${VAR}` and `${VAR:-default}` are replaced anywhere in the file before it is parsed; an unset variable without a default becomes an empty string.

## Full example

```yaml
name: orders_quality                 # required: the run / metrics key
description: Orders feed checks

source:                              # required
  type: csv                          # guessed from path/url if omitted
  path: data/orders.csv
  # cursor: updated_at               # incremental reads (with state.incremental)
  # max_rows: 100000

schema:
  path: orders.schema.yaml           # loaded if it exists, otherwise inferred and saved here
  infer: true

detectors:
  - method: mad
    columns: [quantity, unit_price]
  - method: mad
    columns: [unit_price]
    group_by: region
  - method: iforest
    n_estimators: 200

detection:
  combine: any                       # any | vote | all
  min_votes: 2
  # time_column: timestamp
  # columns: [...]                   # default for specs without columns
  # group_by: region                 # default for specs without group_by

remediation:                         # or `remediation: false` to only report
  dedupe: true
  unattributed: flag
  # flag_column: needs_review
  default:
    missing: auto
    outlier: cap
    invalid: coerce
  columns:
    unit_price: {outlier: flag}
  llm:
    enabled: false
    provider: ollama
    model: llama3.1:8b
    auto_apply: false
    min_confidence: 0.8

review:
  enabled: true
  # db: review.db

alerts:
  rules:
    - {metric: anomaly_rate, op: ">", value: 0.03, severity: warning}
    - {metric: quality_score, op: "<", value: 0.95, severity: error}
    - {metric: anomaly_rate, type: change, op: ">", value: 0.02, severity: warning}
  notifiers:
    - {type: console, min_severity: info}
    - {type: file, path: out/alerts.jsonl}
  rate_limit: {dedup_seconds: 3600, window_seconds: 3600, max_per_window: 20}

sink:
  path: out/orders_clean.csv
  anomalies_path: out/anomalies.json
  report_path: out/remediation.md

monitor:
  store_anomalies: 1000
  auto_tune: false

state:
  incremental: false

schedule:
  every: 1h
```

## name

Required string. Identifies the pipeline in run history, metrics, the review queue, incidents and alert rate limits. Keep it stable.

## description

Optional string shown in the web app.

## source

Required mapping. `type` is one of `csv`, `tsv`, `json`, `jsonl`, `ndjson`, `parquet`, `sql` (`sqlite`, `database`), `rest` (`api`, `http`); when omitted it is guessed from `path` or `url`. Type-specific options are listed in [Sources](/anomalyguard/docs/concepts/sources/#options-per-type).

| Key | Default | Meaning |
|---|---|---|
| `type` | guessed | Source type |
| `path` / `url` | | File path, SQLite file or SQLAlchemy URL (`url` for `sql` and `rest`) |
| `cursor` | | Column whose largest value is remembered for incremental reads |
| `max_rows` | all | Read at most this many rows (non-incremental runs) |
| `name` | pipeline name | Overridden by the pipeline name |

## schema

Mapping, or a string that is taken as `path`.

| Key | Default | Meaning |
|---|---|---|
| `path` | | Schema file. Loaded if it exists; otherwise inferred from the data and saved there on the first run |
| `infer` | `true` | With `path` set and the file missing: `false` makes the run fail instead of inferring |

Without `schema` (or with no `path`), the schema is inferred on every run. See [Schema and quality score](/anomalyguard/docs/concepts/schema-and-quality/).

## detectors

A list of detector names or specs (or a comma-separated string). Default `[mad, iforest]`. At least one is required, and every spec is validated when the file is loaded. See the [Detector reference](/anomalyguard/docs/reference/detectors/#common-parameters) for spec keys and parameters.

## detection

| Key | Default | Meaning |
|---|---|---|
| `combine` | `any` | `any`, `vote` or `all`: when a row counts as anomalous |
| `min_votes` | `1` | For `vote` |
| `time_column` | | Sort by this column before detection (time-series detectors); results map back to the original order |
| `columns` | | Applied to detector specs that do not set `columns` |
| `group_by` | | Applied to detector specs that do not set `group_by` |

## remediation

A mapping, `false` (report only: no changes, no review items), or `true` (all defaults). Default: an empty mapping, which applies the default policy. See [Remediation](/anomalyguard/docs/concepts/remediation/).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` is the same as `remediation: false` |
| `dedupe` | `true` | `true` (primary key, else whole row), a list of columns, or `false` |
| `unattributed` | `flag` | Rows flagged only by multivariate detectors: `flag`, `drop` or `keep` |
| `flag_column` | | Add a boolean column marking rows with flagged values |
| `fix_types` | `true` | Coerce values to schema types |
| `default` | see below | Column policy applied to every column |
| `columns` | | Per-column overrides of `default` |
| `llm` | disabled | LLM suggestions for flagged values (below) |

**Column policy keys**: `missing` (`auto`, `mean`, `median`, `mode`, `ffill`, `bfill`, `interpolate`, `constant`, `drop`, `flag`, `keep`; default `auto`), `outlier` (`cap`, `winsorize`, `clip`, `median`, `mean`, `null`, `flag`, `drop`, `keep`; default `cap`), `invalid` (`coerce`, `drop`, `flag`, `keep`; default `coerce`), `constant`, `min`, `max` (for `clip`), `cap_k` (default `3.5`).

### remediation.llm

See [LLM-assisted remediation](/anomalyguard/docs/guides/llm-remediation/).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Ask a model for a value for each flagged cell |
| `provider` | `ollama` | `ollama` or `openai` (any OpenAI-compatible endpoint) |
| `model` | `llama3.1:8b` | Model name |
| `base_url` | `http://localhost:11434` (ollama), `https://api.openai.com/v1` (openai) | Server URL |
| `api_key_env` | `OPENAI_API_KEY` | Environment variable with the key (sent only for `openai`) |
| `timeout` | `60` | Seconds per request |
| `temperature` | `0.0` | Sampling temperature |
| `auto_apply` | `false` | Write suggestions into the data when confident enough |
| `min_confidence` | `0.8` | Confidence needed for `auto_apply` |
| `max_items` | `20` | At most this many flagged cells per run are sent |

## review

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Put flagged values in the review queue |
| `db` | the monitor database | SQLite file for the review queue |

## alerts

See [Alerts](/anomalyguard/docs/concepts/alerts/) and [Alerts and notifiers](/anomalyguard/docs/guides/alerts/).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns alerting off (failed-run alerts too) |
| `rules` | `anomaly_rate > 0.05` (warning), `quality_score < 0.9` (error) | Alert rules |
| `notifiers` | console when run from the CLI | Delivery channels |
| `rate_limit` | on, with the defaults below | Mapping, or `false` to turn off |

**Rule keys**: `metric` (required), `op` (`>`, `>=`, `<`, `<=`, `==`, `!=`; default `>`), `value` (alias `threshold`; default `0`), `severity` (`debug`, `info`, `warning`, `error`, `critical`; default `warning`), `type` (`threshold` or `change`; default `threshold`), `name`, `message` (format string over the metrics and `observed`).

**Notifier keys**: `type` (`console`, `file` / `jsonl`, `webhook`, `slack`, `email`), `min_severity` (alias `severity`) and the type's options, listed in [Alerts and notifiers](/anomalyguard/docs/guides/alerts/). `url_env` reads a webhook or Slack URL from the environment.

**Rate limit keys**: `dedup_seconds` (`3600`), `window_seconds` (`3600`), `max_per_window` (`20`), `state_path` (default `<state dir>/<name>.alerts.json`).

## sink

Optional. Nothing is written without it.

| Key | Default | Meaning |
|---|---|---|
| `path` | | Cleaned data (the data as read when remediation is off). Format from the extension: `.csv`, `.jsonl` / `.ndjson`, `.json`, `.parquet`, `.db` / `.sqlite`; anything else is CSV |
| `type` | from the extension | `csv`, `jsonl`, `json`, `parquet`, `sqlite` |
| `table` | `cleaned` | Table for SQLite sinks |
| `mode` | `overwrite` | `overwrite` or `append` (CSV, JSONL and SQLite) |
| `anomalies_path` | | Full detection report as JSON |
| `report_path` | | Remediation report: `.md` for Markdown, anything else JSON |

## monitor

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` skips the metrics database: no run history, findings or thresholds |
| `db` | `.anomalyguard/anomalyguard.db` (in the working directory) | Metrics database |
| `store_anomalies` | `1000` | Findings stored per run (highest scores first) for the web app and feedback |
| `auto_tune` | `false` | Tune thresholds from feedback after each run |

## state

| Key | Default | Meaning |
|---|---|---|
| `incremental` | `false` | Resume from the last checkpoint / watermark and read only new rows |
| `dir` | `.anomalyguard/state` (in the working directory) | Checkpoints, run counters, alert history |

## schedule

Used by `anomalyguard run --schedule`.

| Key | Meaning |
|---|---|
| `every` | Interval: `30s`, `5m`, `2h`, `1d` or plain seconds |
| `interval_seconds` | Interval in seconds (takes precedence over `every`) |
