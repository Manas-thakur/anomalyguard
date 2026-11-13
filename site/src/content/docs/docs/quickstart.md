---
title: Quickstart
description: Profile a dataset, detect anomalies, fix what is safe, run a pipeline and open the web app.
---

This walkthrough uses the synthetic orders dataset that AnomalyGuard can generate: 1,000 orders with injected price, quantity and delivery outliers, contextual price anomalies (a price that is normal in one region but not in another), missing values, type errors and duplicates. Every command writes to the current folder, so start in an empty one.

It assumes `anomalyguard` is installed with the `server` extra ([Installation](/anomalyguard/docs/installation/)). In a clone of the repository, prefix each command with `uv run`.

## 1. Generate data

```bash
anomalyguard demo generate -d orders -o orders.csv
```

```
Wrote 1000 rows to orders.csv and ground truth to orders_labels.csv
Injected: contextual=15, duplicate=10, missing=10, point=20, type_error=5
```

`orders_labels.csv` holds the ground truth. The same file ships in the repository as `examples/data/orders.csv`.

## 2. Profile

```bash
anomalyguard profile orders.csv
```

```
orders.csv: 1000 rows x 8 columns

column         type         nulls  unique  invalid  summary
-------------  -----------  -----  ------  -------  -----------------------------------------------------------
order_id       integer      0      990     0        mean=100496.9 std=285 min=100001 median=100498.5 max=100990
timestamp      datetime     0      990     0        2026-01-01 00:00:00 .. 2026-01-21 14:30:00
customer_id    string       0      362     0        C0186(8), C0039(7), C0063(7)
region         categorical  3      4       0        north(308), south(295), east(246)
quantity       integer      4      17      0        mean=6.308 std=29.77 min=1 median=4 max=493
unit_price     float        0      907     5        mean=78.48 std=180.7 min=15.15 median=47.46 max=3454.5
delivery_days  integer      3      16      0        mean=4.318 std=4.676 min=1 median=4 max=84
status         categorical  0      4       0        completed(795), pending(100), returned(54)

Quality score 98.6%  (completeness 99.9%, validity 97.5%, uniqueness 99.0%)
Schema violations: 35 (primary_key: 10, type: 5, unique: 20) in 25 rows
Duplicate rows: 10
```

The schema was inferred. Save it with `--schema-out orders.schema.yaml`, tighten it by hand (ranges, allowed values, required columns), and pass it back with `--schema`. See [Schema and quality score](/anomalyguard/docs/concepts/schema-and-quality/).

## 3. Detect

```bash
anomalyguard detect orders.csv --group-by region -o report.json
```

```
Scanned 1000 rows: 49 anomalous (4.9%), combine=any
By detector: grouped(mad by region)=41, grouped(iforest by region)=49
By column:   (row)=3, delivery_days=13, quantity=10, unit_price=23

Top 10 anomalies (highest score first):
  row 794  score=94.47  votes=2  columns=unit_price
      - [region=east] unit_price=3035 has modified z-score 330.7 vs median 89.08 (threshold 3.5)
      - [region=east] isolation score 0.787 > 0.500; most unusual: unit_price=3035 (robust z 330.9), quantity=5 (robust z 0.7)
  ...
```

The default detectors are `mad` (robust z-score per column) and `iforest` (Isolation Forest). `--group-by region` fits each detector separately per region, which is what catches the contextual price anomalies. Try `-m zscore,lof` or any name from `anomalyguard detectors`. The JSON report has every finding.

## 4. Fix

```bash
anomalyguard fix orders.csv -o orders_clean.csv --group-by region --report fix.md
```

```
Wrote 990 rows to orders_clean.csv
  45 cells fixed, 10 rows dropped, 16 rows flagged for review
  by strategy: cap=25, impute_median=12, impute_mode=3, type_fix=5
  report: fix.md
```

Duplicates were dropped, unparseable values coerced to missing and imputed, and outliers capped to robust fences. Values that a cap could not move were flagged. `fix.md` lists every changed cell with its before and after values and the reason. Add `--review-db review.db` to put the flagged values in a review queue. See [Remediation](/anomalyguard/docs/concepts/remediation/).

## 5. Run a pipeline

A pipeline puts all of the above, plus alerts and run history, into one YAML file:

```bash
anomalyguard init --source orders.csv --name orders     # writes pipeline.yaml
anomalyguard run pipeline.yaml
```

```
Wrote pipeline.yaml (template: csv_quality). Next: anomalyguard run pipeline.yaml
[orders] run #1: 1000 rows, 33 anomalies (3.3%), quality 98.6%, 47 cells fixed, 10 dropped, 6 flagged, 0 alerts, 212 ms
    data: .../out/orders_clean.csv
    anomalies: .../out/orders_anomalies.json
    report: .../out/orders_remediation.md
```

The first run infers `orders.schema.yaml` next to the pipeline. Run history, the review queue and checkpoints go to `.anomalyguard/` in the current folder. `anomalyguard run pipeline.yaml --schedule` repeats it on the interval in the file. See [Pipelines](/anomalyguard/docs/concepts/pipelines/) and the [Pipeline YAML reference](/anomalyguard/docs/reference/pipeline-yaml/).

:::note
`init` writes `--source` into the YAML as given, and paths in the YAML are resolved relative to the YAML file. If you write the pipeline into another folder with `-o`, give `--source` relative to that folder.
:::

## 6. Open the web app

```bash
anomalyguard serve
```

Open `http://127.0.0.1:8765` in a browser. The run you just made is on **Health** and **Runs**, its flagged values are in the **Review inbox**, and **Analyze** walks through the same steps for an uploaded file: upload `orders.csv`, read the profile, pick `mad` and `iforest` grouped by `region`, open the results, preview fixes on **Fix & export** and download the cleaned CSV. See the [Web app guide](/anomalyguard/docs/guides/web-app/).

## 7. Check the setup

```bash
anomalyguard doctor
```

`doctor` checks the state folder, the database, installed extras, pipeline files, notifier secrets and server environment variables. See [Troubleshooting](/anomalyguard/docs/guides/troubleshooting/).

## In Python

```python
import anomalyguard as ag

df = ag.read("orders.csv")
report = ag.detect(df, ["mad", "iforest"], group_by="region")
print(report.summary()["n_anomalies"])          # 49

result = ag.fix(df)                              # dedupe + type fixes + impute + cap
result.data.to_csv("clean.csv", index=False)
print(result.report().to_markdown()[:500])
```

See the [Python API](/anomalyguard/docs/reference/python-api/).
