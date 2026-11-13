---
title: Alerts
description: Alert rules on run metrics, severities, deduplication and rate limits.
---

After every pipeline run, AnomalyGuard evaluates **alert rules** against the run's metrics and sends the alerts that fire to **notifiers**. A failed run always produces a `critical` alert named `pipeline_failure`.

## Rules

A rule compares one metric with a value:

```yaml
alerts:
  rules:
    - {metric: anomaly_rate, op: ">", value: 0.03, severity: warning}
    - {metric: quality_score, op: "<", value: 0.95, severity: error}
    - {metric: anomaly_rate, type: change, op: ">", value: 0.02, severity: warning}
```

- `op`: `>`, `>=`, `<`, `<=`, `==`, `!=`.
- `type: threshold` (default) compares the current value. `type: change` compares the difference from the previous successful run of the same pipeline, and does not fire on the first run.
- `severity`: `debug`, `info`, `warning` (default), `error`, `critical`.
- Optional `name`, and `message`: a Python format string over the metrics plus `observed`, for example `"Anomaly rate {anomaly_rate:.1%} on {rows} rows"`.

A pipeline without an `alerts.rules` key uses two default rules: `anomaly_rate > 0.05` (warning) and `quality_score < 0.9` (error).

## Metrics

Rules can use any numeric run metric: `rows`, `n_anomalies`, `anomaly_rate`, `quality_score`, `completeness`, `validity`, `uniqueness`, `freshness`, `invalid_rows`, `duplicate_rows`, `cells_changed`, `rows_dropped`, `flagged_for_review`. A rule on a metric that is missing for a run (for example `freshness` without a configured timestamp column) does not fire.

## Delivery

Each notifier has a `min_severity` and only receives alerts at or above it. Before sending, a **rate limiter** suppresses:

- **duplicates**: the same source, rule and severity within `dedup_seconds` (default 3600);
- **bursts**: more than `max_per_window` alerts (default 20) within `window_seconds` (default 3600).

The limiter's history is saved per pipeline under `.anomalyguard/state/`, so it works across separate `anomalyguard run` processes. Set `rate_limit: false` to turn it off.

Every alert is recorded with the run, with a status of `sent`, `duplicate`, `rate_limited`, `failed` (no notifier delivered it) or `filtered` (no notifier accepts that severity). The web app shows them on the run's **Alerts** tab.

See [Alerts and notifiers](/anomalyguard/docs/guides/alerts/) for the console, file, webhook, Slack and email notifiers.
