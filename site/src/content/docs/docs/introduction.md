---
title: Introduction
description: What AnomalyGuard is, what it does, and what it does not do.
---

AnomalyGuard is a Python package for finding and fixing problems in tabular data. It reads data from files, databases, REST APIs or in-memory streams, validates it against a schema, finds anomalies with statistical, machine-learning, time-series and contextual detectors, and repairs what a policy says is safe to repair. Anything it cannot fix safely goes to a human review queue. It sends alerts when quality drops, records every run in SQLite, and includes a local web app for analysing files, triaging incidents and working through the review queue.

The current version is **0.3.0**. It is MIT licensed, single-user and local-first.

## What it does

- **Ingest**: CSV, TSV, JSON, JSONL, Parquet, SQLite and any SQLAlchemy database, paginated REST APIs and in-memory streams. A cursor column makes reads incremental. See [Sources](/anomalyguard/docs/concepts/sources/).
- **Validate**: infer or load a schema, coerce types and compute a quality score from completeness, validity, uniqueness and freshness. See [Schema and quality score](/anomalyguard/docs/concepts/schema-and-quality/).
- **Detect**: eleven detectors (z-score, MAD, IQR, Grubbs, Isolation Forest, LOF, k-NN, rolling z-score, EWMA, seasonal residual, CUSUM) plus the `grouped` (per-group) and `ensemble` wrappers. Every flag carries a reason. See [Detectors](/anomalyguard/docs/concepts/detectors/).
- **Remediate**: dedupe, fix types, impute missing values, cap or winsorize outliers, clip to schema ranges, drop or flag, with a policy per column. See [Remediation](/anomalyguard/docs/concepts/remediation/).
- **Review and learn**: flagged values go to a review queue. Marking findings as false positives raises that detector's threshold. See [Review and feedback loop](/anomalyguard/docs/concepts/review-and-feedback/).
- **Alert**: rules on run metrics, delivered to the console, a JSONL file, a webhook, Slack or email, with deduplication and rate limits. See [Alerts](/anomalyguard/docs/concepts/alerts/).
- **Monitor**: every pipeline run and analysis is stored in SQLite. The web app groups findings into [incidents](/anomalyguard/docs/concepts/incidents/), shows the health of every source and runs pipelines as background jobs. See the [Web app guide](/anomalyguard/docs/guides/web-app/).

The stages are wired together by a declarative [pipeline YAML](/anomalyguard/docs/concepts/pipelines/) that you run from the CLI, on an interval, or from the web app. Each stage is also a Python module you can use on its own.

## Design choices

- **Readable algorithms.** Isolation Forest, LOF, k-NN distance, Grubbs, CUSUM, EWMA and seasonal decomposition are implemented in plain NumPy. SciPy supplies only the t-distribution (Grubbs) and the KD-tree neighbour search (LOF, k-NN). scikit-learn is not required.
- **Every flag has a reason.** Each finding names the detector, the column and the value, for example `[region=east] unit_price=3035 has modified z-score 330.7 vs median 89.08 (threshold 3.5)`.
- **Fix only what is safe.** Remediation is set per column. Values that a robust cap cannot move, such as contextual anomalies, are flagged for review instead of being rewritten.
- **Small and local.** One Python package backed by SQLite. The web app is built with React and ships prebuilt inside the package, so no Node.js is needed to run it.

## What it is not

- It is **not multi-user**. There are no accounts or roles; the web app and API can be protected with one shared API key.
- Web app uploads are **analysed in memory**, so very large files need a machine with enough RAM.
- Scheduling is **interval-based** (`anomalyguard run --schedule` or `--every 5m`). There are no cron expressions, and the web app runs pipelines on demand only.
- The benchmark datasets are **synthetic**. They show which detector suits which anomaly type, not how the detectors will do on your data.

## Where to go next

- [Installation](/anomalyguard/docs/installation/): pip, extras, uv, Docker.
- [Quickstart](/anomalyguard/docs/quickstart/): profile, detect, fix, run a pipeline and open the web app in a few minutes.
- [CLI reference](/anomalyguard/docs/reference/cli/) and [Python API](/anomalyguard/docs/reference/python-api/).
