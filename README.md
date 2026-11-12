# AnomalyGuard

**Data anomaly detection and remediation, with the algorithms built from scratch.**

[![CI](https://github.com/Manas-thakur/anomalyguard/actions/workflows/ci.yml/badge.svg)](https://github.com/Manas-thakur/anomalyguard/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

AnomalyGuard reads data from files, databases, APIs or streams. It validates the data against a schema, finds anomalies with statistical, ML, time-series and contextual detectors, and fixes what is safe to fix. Anything it can't fix safely goes to a human review queue. It sends alerts when quality drops and records every run in a small dashboard, where false-positive feedback adjusts detector thresholds.

## Philosophy

Most AI systems fail because of bad data, not bad models. AnomalyGuard is a modular, pipeline-based system that watches data quality, fixes common problems, alerts people when needed, and learns from their feedback.

- **From scratch, readable algorithms.** The plans in [`plans/`](plans/) call for components built from scratch. Isolation Forest, LOF, k-NN distance, Grubbs, CUSUM, EWMA and seasonal decomposition are all implemented in plain NumPy. SciPy supplies only the t-distribution and KD-tree neighbour search. scikit-learn is not required.
- **Every flag has a reason.** Each anomaly names the detector, the column and the value, and explains why it was flagged, for example `[region=north] unit_price=157.1 has modified z-score 77.1 vs median 19.89 (threshold 3.5)`.
- **Fix only what is safe, and flag the rest.** Remediation policies are set per column. Values that a robust cap can't move, such as contextual anomalies, go to a review queue instead of being rewritten silently.
- **Small and local.** It's one Python package backed by SQLite, and the dashboard needs no build step.

## Architecture

```
Sources: CSV/TSV, JSON/JSONL, Parquet, SQLite/SQL, REST API, in-memory streams
    |
    v
ingest     connectors, schema inference, checkpoints + watermark (incremental reads)
    |
    v
schema     registry (YAML/JSON), validation, type coercion, quality score
    |
    v
detect     statistical | ML (from scratch) | time-series | grouped | ensemble  -> reasons
    |
    v
remediate  dedupe, type fixes, impute, cap/winsorize/clip, drop, flag -> review queue (+ optional LLM)
    |
    v
alert      rules on run metrics -> console, JSONL file, webhook, Slack, email (rate-limited, deduplicated)
    |
    v
monitor    SQLite metrics store, FastAPI + static dashboard, feedback loop -> threshold tuning
```

The `pipeline` package wires these stages together from a YAML file, adds a sink, persisted state and an interval scheduler. The `demo` package generates labelled synthetic data and benchmarks every detector.

## Installation

Requires Python 3.10 or newer.

```bash
# library + CLI
pip install "git+https://github.com/Manas-thakur/anomalyguard"

# with the dashboard server, Parquet and SQLAlchemy (PostgreSQL/MySQL/...) support
pip install "anomalyguard[server,parquet,sql] @ git+https://github.com/Manas-thakur/anomalyguard"
```

| Extra | Adds | Needed for |
|---|---|---|
| `server` | fastapi, uvicorn | `anomalyguard serve` (dashboard + REST API) |
| `parquet` | pyarrow | Parquet sources and sinks |
| `sql` | sqlalchemy | non-SQLite databases (SQLite works without it) |
| `all` | all of the above | |

### Development setup (uv)

```bash
git clone https://github.com/Manas-thakur/anomalyguard
cd anomalyguard
uv sync --all-extras          # creates .venv with dev tools (pytest, ruff) and all extras
uv run pytest -q
uv run ruff check .
```

## Quick start

Run these from the repository root. `examples/data/orders.csv` contains 1,000 synthetic orders with injected anomalies: price, quantity and delivery outliers, contextual price anomalies, missing values, type errors and duplicates. The ground truth is in `orders_labels.csv`.

```bash
# 1. Profile: inferred types, statistics and a quality score
uv run anomalyguard profile examples/data/orders.csv

# 2. Detect: robust z-score + Isolation Forest, computed within each region
uv run anomalyguard detect examples/data/orders.csv --group-by region -o out/report.json

# 3. Fix: dedupe, repair types, impute, cap outliers, flag the rest
uv run anomalyguard fix examples/data/orders.csv -o out/orders_clean.csv --group-by region --report out/fix_report.md

# 4. Run a declarative pipeline (validation, detection, remediation, alerts, sink, metrics)
uv run anomalyguard run examples/pipeline.yaml

# 5. Open the dashboard at http://127.0.0.1:8765
uv run anomalyguard serve
```

If you installed with pip, drop the `uv run` prefix. Example output from step 2:

```
Scanned 1000 rows: 49 anomalous (4.9%), combine=any
By detector: grouped(mad by region)=41, grouped(iforest by region)=49
By column:   (row)=3, delivery_days=13, quantity=10, unit_price=23

Top 3 anomalies (highest score first):
  row 794  score=94.47  votes=2  columns=unit_price
      - [region=east] unit_price=3035 has modified z-score 330.7 vs median 89.08 (threshold 3.5)
      - [region=east] isolation score 0.787 > 0.500; most unusual: unit_price=3035 (robust z 330.9), quantity=5 (robust z 0.7)
  ...
```

Step 3 prints `Wrote 990 rows ... 45 cells fixed, 10 rows dropped, 16 rows flagged for review`. The Markdown report lists every changed cell with its before and after values, the strategy used and the reason.

To start your own pipeline:

```bash
anomalyguard init --source data/my_table.csv --name my_table   # writes pipeline.yaml
anomalyguard run pipeline.yaml
anomalyguard run pipeline.yaml --schedule                       # repeat on the schedule in the file
```

## CLI reference

| Command | What it does |
|---|---|
| `anomalyguard profile FILE [--schema-out schema.yaml] [--json]` | Infer a schema, profile columns and compute completeness, validity, uniqueness, freshness and an overall quality score |
| `anomalyguard validate FILE --schema schema.yaml` | Validate against a schema; exits 1 if any rule fails |
| `anomalyguard detect FILE [-m mad,iforest] [--columns a,b] [--group-by col] [--time-column ts] [--combine any\|vote\|all] [--contamination 0.05] [-o report.json] [--fail-on-anomalies]` | Detect anomalies and print the top rows with reasons |
| `anomalyguard fix FILE -o clean.csv [-m mad] [--missing auto] [--outlier cap] [--invalid coerce] [--no-dedupe] [--report fix.md] [--review-db review.db]` | Detect and remediate, then write the cleaned data and a report |
| `anomalyguard run PIPELINE.yaml [...] [--schedule \| --every 5m] [--max-runs N] [--json]` | Run one or more pipelines once or on an interval |
| `anomalyguard init [-t csv_quality\|timeseries_monitor\|database_quality] [--source ...] [-o pipeline.yaml]` | Write a starter pipeline (`--list` shows templates) |
| `anomalyguard demo generate [-d orders\|sensor\|tabular] [-n ROWS] [-o out.csv]` | Generate synthetic data with ground-truth labels |
| `anomalyguard demo benchmark [--datasets tabular,orders,sensor] [-o results.md]` | Precision, recall, F1 and ROC-AUC of every detector |
| `anomalyguard serve [--db .anomalyguard/anomalyguard.db] [--host] [--port 8765]` | Dashboard and REST API (needs the `[server]` extra) |
| `anomalyguard review list\|approve ID [--value V]\|reject ID` | Work through the human review queue |
| `anomalyguard feedback fp\|tp --anomaly-id N`, `feedback stats`, `feedback tune` | Record false and true positives and retune thresholds |
| `anomalyguard detectors` | List the available detectors |

Input files can be `.csv`, `.tsv`, `.json`, `.jsonl`/`.ndjson` or `.parquet`, optionally compressed with `.gz`. SQLite files (`.db`) need `--table`. `python -m anomalyguard` works too.

## Python API

```python
import anomalyguard as ag
from anomalyguard.detect import GroupedDetector, IsolationForestDetector, MADDetector, run_detectors
from anomalyguard.remediate import RemediationPipeline
from anomalyguard.schema import Schema

df = ag.read("examples/data/orders.csv")

# quality profile against a hand-tuned schema
schema = Schema.load("examples/orders.schema.yaml")
prof = ag.profile(df, schema=schema)
print(prof.quality.score, prof.validation.counts_by_rule())

# one-liners
report = ag.detect(df, ["mad", "iforest"], group_by="region")
result = ag.fix(df)  # dedupe + type fixes + impute + cap
result.data.to_csv("clean.csv", index=False)
print(result.report().to_markdown())

# full control
cols = ["quantity", "unit_price", "delivery_days"]
report = run_detectors(
    df,
    [
        MADDetector(columns=cols),
        GroupedDetector(MADDetector(columns=["unit_price"]), group_by="region"),
        IsolationForestDetector(columns=cols, n_estimators=200),
    ],
)
for rec in report.records(limit=5):
    print(rec["index"], rec["score"], rec["reasons"])

policy = {
    "default": {"missing": "auto", "outlier": "cap"},
    "columns": {"unit_price": {"outlier": "flag"}},
}
result = RemediationPipeline(policy, schema=schema).run(df, report)
```

Every detector follows the same interface: `fit(df)`, `score(df)`, `predict(df)`, and `detect(df)`, which returns labels, normalised scores and findings with reasons. [`examples/api_example.py`](examples/api_example.py) walks through all six stages: ingest, schema, detect, remediate, review queue and alerts.

## Pipeline YAML reference

Paths for data, schema and sink are resolved relative to the YAML file. Runtime state lives in `./.anomalyguard/` by default (metrics DB, review queue, checkpoints, alert rate-limit history), so `anomalyguard serve` finds it with no flags. `${VAR}` and `${VAR:-default}` are replaced with environment variables.

```yaml
name: orders_quality                 # required, used as the run/metrics key
description: Orders feed checks

source:                              # required
  type: csv                          # csv | json | jsonl | parquet | sql | rest (guessed from path if omitted)
  path: data/orders.csv
  # cursor: updated_at               # incremental: only rows with a larger value are read next time
  # max_rows: 100000
  # sql:  {type: sql, url: data.db | postgresql://..., table: events | query: "SELECT ...", cursor: id}
  # rest: {type: rest, url: https://..., records_path: data.items, api_key_env: API_TOKEN,
  #        pagination: {type: page|offset|cursor|next_link, ...}}

schema:
  path: orders.schema.yaml           # loaded if it exists; otherwise inferred and saved there
  infer: true

detectors:                           # names or specs; see the detector table
  - method: mad
    columns: [quantity, unit_price]
  - method: mad
    columns: [unit_price]
    group_by: region                 # contextual detection per group
  - method: iforest
    n_estimators: 200                # any constructor parameter can be given inline
  # - method: ensemble
  #   detectors: [mad, lof, knn]
  #   combine: vote                   # mean | max | vote | weighted
  #   min_votes: 2

detection:
  combine: any                       # any | vote | all, across the detectors above
  min_votes: 2
  # time_column: timestamp           # sort before time-series detectors
  # columns: [...] / group_by: col   # defaults applied to every detector spec

remediation:                         # or `remediation: false` to only report
  dedupe: true                       # true (primary key or full row) | [col, ...] | false
  unattributed: flag                 # rows flagged by multivariate detectors: flag | drop | keep
  # flag_column: needs_review        # add a boolean column to the output
  default:
    missing: auto                    # auto | mean | median | mode | ffill | bfill | interpolate | constant | drop | flag | keep
    outlier: cap                     # cap | winsorize | clip | median | mean | null | flag | drop | keep
    invalid: coerce                  # coerce (-> missing -> imputed) | drop | flag | keep
  columns:
    unit_price: {outlier: flag}
  llm:                               # optional, disabled unless enabled: true
    enabled: false
    provider: ollama                 # ollama | openai (any OpenAI-compatible endpoint)
    model: llama3.1:8b
    # base_url: http://localhost:11434
    # api_key_env: OPENAI_API_KEY
    auto_apply: false                # true: apply suggestions with confidence >= min_confidence
    min_confidence: 0.8

review:
  enabled: true                      # flagged items go to the SQLite review queue
  # db: review.db                    # default: the monitor DB

alerts:
  rules:
    - {metric: anomaly_rate, op: ">", value: 0.03, severity: warning}
    - {metric: quality_score, op: "<", value: 0.95, severity: error}
    - {metric: anomaly_rate, type: change, op: ">", value: 0.02, severity: warning}  # vs previous run
  notifiers:
    - {type: console, min_severity: info}
    - {type: file, path: out/alerts.jsonl}
    - {type: slack, url: "${SLACK_WEBHOOK_URL}", min_severity: error}
    - {type: webhook, url: "https://example.com/hook", headers: {X-Token: "${HOOK_TOKEN}"}}
    - {type: email, host: smtp.example.com, to_addrs: [ops@example.com], username: bot,
       password_env: ANOMALYGUARD_SMTP_PASSWORD, min_severity: critical}
  rate_limit: {dedup_seconds: 3600, window_seconds: 3600, max_per_window: 20}

sink:
  path: out/orders_clean.csv         # .csv | .jsonl | .json | .parquet | .db (+ table:)
  anomalies_path: out/anomalies.json
  report_path: out/remediation.md    # .md or .json

monitor:
  # db: .anomalyguard/anomalyguard.db
  store_anomalies: 1000              # findings kept per run for the dashboard
  auto_tune: false                   # apply feedback-based threshold tuning after each run

state:
  incremental: false                 # resume from the last checkpoint/watermark
  # dir: .anomalyguard/state

schedule:
  every: 1h                          # used by --schedule (or interval_seconds: 3600)
```

The alert rules can use these metrics: `rows`, `n_anomalies`, `anomaly_rate`, `quality_score`, `completeness`, `validity`, `uniqueness`, `freshness`, `invalid_rows`, `duplicate_rows`, `cells_changed`, `rows_dropped`, `flagged_for_review`. If a pipeline fails, the run is recorded as failed and a `critical` alert is sent.

## Detectors

| Name | Category | How it works | Default threshold |
|---|---|---|---|
| `zscore` | statistical | `abs(x - mean) / std` per column | 3.0 |
| `mad` | statistical | Modified z-score `0.6745 * abs(x - median) / MAD`; robust to contamination | 3.5 |
| `iqr` | statistical | Tukey fences: distance outside [Q1, Q3] in IQR units | 1.5 |
| `grubbs` | statistical | Iterative two-sided Grubbs test; scores against the cleaned mean and std | alpha = 0.05 |
| `iforest` | ML | Isolation Forest (random isolation trees, `2^(-E[h]/c(n))`) | auto: median + 4 MAD of training scores (min 0.5) |
| `lof` | ML | Local Outlier Factor (reachability distance, local reachability density) | auto: median + 6 MAD (min 1.2) |
| `knn` | ML | Mean distance to the k nearest neighbours in robust-scaled space | auto: median + 6 MAD |
| `rolling_zscore` | time series | Deviation from a trailing window (rolling median/IQR, or mean/std) | 4.0, window 24 |
| `ewma` | time series | Residual from an EWMA forecast; spikes are clipped before the state updates | 4.0, span 24 |
| `seasonal` | time series | Robust decomposition (rolling-median trend + per-phase seasonal profile), robust z of residual | 4.0, period 24 |
| `cusum` | time series | Two-sided tabular CUSUM on robust-standardised (optionally de-seasonalised) values | h = 5, k = 1.0 |
| `grouped` | contextual | Any detector fitted separately per group (`group_by`); small groups fall back to a global baseline | per base detector |
| `ensemble` | ensemble | `mean`, `max` or `weighted` of normalised scores, or `vote` with `min_votes` | 1.0 normalised |

Every raw score is divided by its threshold, so a normalised score above 1.0 always means anomalous, whichever detector produced it. Any detector also accepts `contamination=0.05`, which flags a fixed share of the data. ML detectors median-impute missing values and scale features robustly. Univariate detectors name the offending column. Multivariate detectors report the most unusual columns as an explanation.

## Benchmark

These are real numbers from `anomalyguard demo benchmark` (seed 42) on the three synthetic datasets, using each detector's default threshold. To reproduce them: `uv run anomalyguard demo benchmark`.

**tabular**: 2,000 rows of correlated 6-D Gaussian data with 100 anomalies. Half are `point` anomalies, where one feature is 6 to 10 standard deviations out. The other half are `correlation` anomalies, where each feature is in range but the joint structure is broken.

| Detector | Precision | Recall | F1 | ROC-AUC | Recall: point | Recall: correlation |
|---|---|---|---|---|---|---|
| zscore | 0.85 | 0.50 | 0.63 | 0.804 | 1.00 | 0.00 |
| mad | 0.91 | 0.50 | 0.65 | 0.804 | 1.00 | 0.00 |
| iqr | 0.52 | 0.51 | 0.51 | 0.803 | 1.00 | 0.02 |
| grubbs | 1.00 | 0.50 | 0.67 | 0.804 | 1.00 | 0.00 |
| iforest | 0.24 | 0.27 | 0.26 | 0.828 | 0.54 | 0.00 |
| **lof** | 0.81 | **0.88** | **0.84** | **0.975** | 1.00 | **0.76** |
| knn | 0.92 | 0.70 | 0.80 | 0.959 | 1.00 | 0.40 |
| ensemble vote (mad + lof + knn, 2 of 3) | 0.92 | 0.70 | 0.80 | 0.937 | 1.00 | 0.40 |

**orders**: 2,000 orders. Unit prices depend on the region, and the data has 40 point anomalies and 30 contextual ones (a west-region price on a north or south order). Only `quantity`, `unit_price` and `delivery_days` are scored.

| Detector | Precision | Recall | F1 | ROC-AUC | Recall: point | Recall: contextual |
|---|---|---|---|---|---|---|
| zscore | 1.00 | 0.51 | 0.68 | 0.871 | 0.90 | 0.00 |
| mad | 0.71 | 0.57 | 0.63 | 0.943 | 1.00 | 0.00 |
| iqr | 0.45 | 0.60 | 0.52 | 0.899 | 1.00 | 0.07 |
| iforest | 0.66 | 0.60 | 0.63 | 0.922 | 1.00 | 0.07 |
| lof | 0.18 | 0.60 | 0.27 | 0.799 | 1.00 | 0.07 |
| **mad by region** | **0.81** | **1.00** | **0.90** | **1.000** | 1.00 | **1.00** |
| iqr by region | 0.50 | 1.00 | 0.66 | 1.000 | 1.00 | 1.00 |

**sensor**: 1,440 hourly readings with a daily cycle and 150 anomalous points: 10 point, 8 contextual (daytime peak values at night), 24 collective (two 12-hour level shifts) and 108 drift.

| Detector | Precision | Recall | F1 | ROC-AUC | point | contextual | collective | drift |
|---|---|---|---|---|---|---|---|---|
| zscore | 1.00 | 0.01 | 0.01 | 0.595 | 0.10 | 0.00 | 0.00 | 0.00 |
| mad | 0.00 | 0.00 | 0.00 | 0.584 | 0.00 | 0.00 | 0.00 | 0.00 |
| rolling_zscore (window 6) | 0.18 | 0.19 | 0.18 | 0.545 | 0.90 | 0.38 | 0.04 | 0.14 |
| ewma (span 3) | 0.47 | 0.13 | 0.20 | 0.560 | 0.90 | 0.62 | 0.04 | 0.04 |
| seasonal (period 24) | 1.00 | 0.23 | 0.37 | 0.657 | 1.00 | 1.00 | 0.67 | 0.00 |
| cusum (period 24) | 0.88 | 0.87 | 0.87 | 0.994 | 0.00 | 0.00 | 0.92 | 1.00 |
| iforest | 0.59 | 0.41 | 0.48 | 0.702 | 1.00 | 0.25 | 0.12 | 0.43 |
| **ensemble max (seasonal + cusum)** | **0.89** | **0.99** | **0.94** | **0.997** | 1.00 | 1.00 | 0.96 | 1.00 |

Schema validation on the `orders` data, using an inferred schema with every column marked required, caught 20 of 20 missing values, 10 of 10 type errors and 20 of 20 duplicates.

What the results show:

- Univariate detectors catch extreme values but cannot see broken correlations. LOF and k-NN can.
- Global detectors miss contextual anomalies in grouped data. Detecting within each group fixes that.
- On seasonal series, the seasonal residual catches point and contextual anomalies, and CUSUM catches sustained shifts and drift. Combined, they recover 99% of the anomalies.
- Isolation Forest matches scikit-learn's implementation on these data (ROC-AUC 0.828 vs 0.830 in a side-by-side check). It struggles here because axis-parallel splits fit correlated features poorly.

These are synthetic datasets built to exercise each anomaly type. The results don't tell you how the detectors will do on your data.

## Remediation

The pipeline works through each problem type in order:

1. **Duplicates**: rows that duplicate the primary key (or the whole row) are dropped.
2. **Type errors**: values are coerced to the schema type. Unparseable values such as `"unknown"` in a numeric column become missing.
3. **Outliers**: only cells that a detector attributed to a column are touched.
   - `cap` clips to the robust fences `median +/- 3.5 MAD/0.6745`.
   - `winsorize` clips to the 1st and 99th percentiles.
   - `clip` uses an explicit `[min, max]`.
   - `median` and `mean` replace the value.
   - `null`, `drop` and `flag` do what their names say.
   - A value that `cap` can't move, such as a contextual anomaly, is flagged instead.
4. **Schema constraints**: values outside `min`/`max` are clipped. Categories are fixed when they differ only in case or whitespace. Other disallowed values are flagged.
5. **Missing values**: the `auto` policy uses the median for numbers and the mode for categoricals, and flags ids, free text and datetimes.
6. **Review queue**: everything flagged goes to SQLite. Approve or reject items in the dashboard, with `anomalyguard review` or with `ReviewQueue`. `ReviewQueue.apply(df)` writes the approved values back.

The optional `LLMSuggester` sends the full record and the problem to Ollama (`/api/generate`) or to any OpenAI-compatible `/chat/completions` endpoint, and attaches a `{value, confidence, rationale}` suggestion to the review item. It is off by default. It applies a suggestion automatically only when `auto_apply: true` is set and the confidence is at least `min_confidence`.

## Dashboard and feedback loop

`anomalyguard serve` starts a FastAPI app. It serves one static HTML page with no build step and no CDN: the charts are inline SVG, and light and dark themes are supported. The page shows:

- summary cards
- anomaly rate and quality score over time
- the runs table, with drill-down into each run's anomalies and their reasons
- **False positive** and **Confirm** buttons on each anomaly
- the review queue, with approve (optionally with a corrected value) and reject
- feedback precision and current threshold multipliers per detector
- recent alerts

**Feedback loop.** Feedback is stored per detector. `feedback tune` (or the **Tune thresholds** button) needs at least 3 new reviews for a detector. If its precision over those reviews is below 80%, its threshold multiplier rises by 15%. If precision is at least 95%, the multiplier relaxes back toward 1.0. The next pipeline run applies the multipliers, and so does every run when `monitor.auto_tune: true` is set.

REST endpoints (OpenAPI docs at `/api/docs`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/api/summary` | totals, pipelines, last run, review counts, thresholds |
| GET | `/api/runs?limit=&pipeline=` / `/api/runs/{id}` / `/api/runs/{id}/anomalies` | run history and findings |
| GET | `/api/alerts` | recent alerts |
| GET / POST | `/api/review?status=` / `/api/review/{id}/approve` / `/api/review/{id}/reject` | review queue |
| POST / GET | `/api/feedback` | record feedback (`anomaly_id`, `label`) / precision per detector |
| POST | `/api/feedback/tune` | adjust thresholds from feedback |
| GET | `/api/thresholds` | current multipliers |

The original plan called for a React and TypeScript dashboard. It was replaced by this single self-contained page so that the project installs with `pip` alone.

## Configuration

| Setting | Where |
|---|---|
| Metrics DB, review queue | `.anomalyguard/anomalyguard.db` (override with `monitor.db` and `review.db`, or `--db`) |
| Checkpoints, run counters, alert history | `.anomalyguard/state/` (override with `state.dir`) |
| Secrets | Read from environment variables: `${VAR}` in YAML, `api_key_env`, `password_env`, `url_env` |
| SMTP password | `ANOMALYGUARD_SMTP_PASSWORD` (default `password_env`) |
| LLM key | `OPENAI_API_KEY` (default `api_key_env` for `provider: openai`) |
| Logging | `anomalyguard -v ...` for debug logs and full tracebacks |

## Docker

```bash
docker build -t anomalyguard .
docker run --rm -p 8765:8765 -v "$PWD/.anomalyguard:/data/.anomalyguard" anomalyguard        # dashboard
docker run --rm anomalyguard detect examples/data/orders.csv --group-by region                 # bundled example
docker run --rm -v "$PWD:/data" anomalyguard run pipeline.yaml                                  # your pipeline
```

## Project layout

```
src/anomalyguard/
  ingest/      base.py (Source, Checkpoint), files.py (CSV/JSON/Parquet), sql.py, rest.py, stream.py,
               inference.py (schema inference, profiling), incremental.py, factory.py
  schema/      registry.py, validator.py, coercion.py, quality.py
  detect/      base.py, statistical.py, ml.py, timeseries.py, contextual.py, ensemble.py,
               registry.py, runner.py, report.py, evaluation.py
  remediate/   strategies.py, pipeline.py, review.py, llm.py, report.py
  alert/       base.py, notifiers.py, rules.py, manager.py
  monitor/     store.py, feedback.py, api.py, static/dashboard.html
  pipeline/    config.py, executor.py, scheduler.py, state.py, sinks.py, templates.py
  demo/        generator.py, benchmark.py
  api.py       read / profile / detect / fix
  cli.py       anomalyguard command
examples/      data/ (orders, sensor + labels), pipeline.yaml, sensor_pipeline.yaml,
               orders.schema.yaml, api_example.py
plans/         the original design documents
tests/         pytest suite (offline, ~10 s)
```

## Development

```bash
uv sync --all-extras
uv run pytest -q                 # 96 tests, all offline (HTTP and SMTP are mocked)
uv run ruff check . && uv run ruff format --check .
uv run anomalyguard demo benchmark
```

CI runs ruff, pytest and a CLI smoke test on Python 3.10, 3.11 and 3.12, and builds the Docker image ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Roadmap: not yet implemented from `plans/`

The design documents in [`plans/`](plans/) are broader than this release. These parts are not built yet:

- **Ingest**: Kafka source, file-watch source, OAuth and Avro/Protobuf for APIs, S3/HTTP paths other than what pandas handles natively. The API is synchronous, not `async`.
- **Detect**: One-Class SVM, autoencoder, DBSCAN, GMM, CDF detector, Holt-Winters, ARIMA, PELT, cross-feature detector, LLM plausibility detector, stacking ensemble, and threshold optimisation against labelled validation data.
- **Remediate**: KNN and model-based imputation, plus transformation helpers (currency, phone, unit, date normalisation). Review is asynchronous through the queue; there is no blocking review gate with timeouts or notifications.
- **Alert**: compound (AND/OR) rules, freshness and no-data rules, message templates.
- **Monitor**: PostgreSQL metrics storage, per-detector latency tracking, and false-negative feedback ("missed anomaly").
- **Pipeline**: cron expressions (only intervals are supported), and processing per micro-batch for unbounded streams (each run reads the available batch).
- **Demo**: real-world datasets, detection-delay and memory metrics, plots and notebooks.
- **Project**: the TypeScript CLI and React dashboard were replaced by the Python CLI and the static dashboard. The Astro blog/docs site is not started.

## License

MIT (c) 2026 Manas Thakur. See [LICENSE](LICENSE).
