"""Built-in pipeline templates used by ``anomalyguard init``."""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "csv_quality": """\
# AnomalyGuard pipeline: scan a CSV file for data-quality issues and anomalies.
# Paths are relative to this file. Run with:  anomalyguard run {filename}
name: {name}
description: Quality scan of a CSV file

source:
  type: csv
  path: {source}

schema:
  # Inferred on the first run and saved here; edit it to tighten the rules.
  path: {name}.schema.yaml
  infer: true

detectors:
  - method: mad          # robust per-column outliers
  - method: iforest      # multivariate outliers
{group_line}
detection:
  combine: any           # any | vote | all

remediation:
  dedupe: true
  default:
    missing: auto        # median for numbers, mode for categories, flag ids/text
    outlier: cap         # clip to robust fences; contextual outliers go to review
    invalid: coerce      # unparseable values -> missing -> imputed

alerts:
  rules:
    - metric: anomaly_rate
      op: ">"
      value: 0.05
      severity: warning
    - metric: quality_score
      op: "<"
      value: 0.9
      severity: error
  notifiers:
    - type: console
      min_severity: info
    - type: file
      path: out/alerts.jsonl
    # - type: slack
    #   url: ${{SLACK_WEBHOOK_URL}}
    #   min_severity: error

sink:
  path: out/{name}_clean.csv
  anomalies_path: out/{name}_anomalies.json
  report_path: out/{name}_remediation.md

schedule:
  every: 1h              # used by: anomalyguard run {filename} --schedule
""",
    "timeseries_monitor": """\
# AnomalyGuard pipeline: monitor a time series (e.g. sensor readings).
name: {name}
description: Time-series monitoring with seasonal and change-point detection

source:
  type: csv
  path: {source}

detectors:
  - method: seasonal
    columns: [{value_column}]
    period: 24           # samples per season (24 for hourly data with daily cycles)
  - method: cusum
    columns: [{value_column}]
    period: 24
  - method: rolling_zscore
    columns: [{value_column}]
    window: 6

detection:
  time_column: timestamp

remediation:
  dedupe: false
  default:
    missing: interpolate
    outlier: flag        # never rewrite sensor history automatically

alerts:
  rules:
    - metric: anomaly_rate
      op: ">"
      value: 0.02
      severity: warning
  notifiers:
    - type: console

sink:
  anomalies_path: out/{name}_anomalies.json

schedule:
  every: 5m
""",
    "database_quality": """\
# AnomalyGuard pipeline: validate a database table incrementally.
name: {name}
description: Incremental data-quality checks on a SQL table

source:
  type: sql
  url: {source}            # sqlite file path, or any SQLAlchemy URL with anomalyguard[sql]
  table: {table}
  cursor: {cursor}         # only rows with a larger cursor value are read on later runs

state:
  incremental: true

detectors:
  - method: iqr
  - method: iforest

remediation: false         # report only; do not modify data

alerts:
  rules:
    - metric: validity
      op: "<"
      value: 0.98
      severity: error
  notifiers:
    - type: console

sink:
  anomalies_path: out/{name}_anomalies.json

schedule:
  every: 15m
""",
}

TEMPLATE_DEFAULTS = {
    "csv_quality": {"source": "data.csv", "group_by": ""},
    "timeseries_monitor": {"source": "data.csv", "value_column": "value"},
    "database_quality": {"source": "data.db", "table": "events", "cursor": "id"},
}


def render_template(
    template: str = "csv_quality",
    name: str = "my_pipeline",
    filename: str = "pipeline.yaml",
    **values: str,
) -> str:
    if template not in TEMPLATES:
        raise KeyError(f"Unknown template '{template}'. Available: {', '.join(TEMPLATES)}")
    params = {**TEMPLATE_DEFAULTS[template], **{k: v for k, v in values.items() if v is not None}}
    group_by = params.pop("group_by", "")
    group_line = (
        f"  - method: mad\n    group_by: {group_by}   # contextual outliers within each group\n"
        if group_by
        else ""
    )
    return TEMPLATES[template].format(name=name, filename=filename, group_line=group_line, **params)
