---
title: Benchmarks
description: Precision, recall, F1 and ROC-AUC of every detector on three labelled synthetic datasets - the full output of anomalyguard demo benchmark.
---

These are the real results of `anomalyguard demo benchmark` (seed 42) on three synthetic datasets with labelled anomalies. Every detector runs at its **default threshold**; precision, recall and F1 count rows flagged at that threshold, and ROC-AUC is computed from the raw scores. Reproduce them with:

```bash
anomalyguard demo benchmark                  # Markdown tables
anomalyguard demo benchmark --json -o results.json
```

:::caution
The datasets are synthetic and built to exercise one anomaly type at a time. The results show which detector suits which kind of anomaly. They do not tell you how the detectors will do on your data. The `Time (s)` column depends on the machine.
:::

## Datasets

- **tabular**: 2,000 rows of correlated 6-dimensional Gaussian data with 100 anomalies. Half are `point` anomalies (one feature 6 to 10 standard deviations out). The other half are `correlation` anomalies: every feature is in range, but the joint structure is broken.
- **orders**: 2,000 orders whose unit prices depend on the region, with 40 `point` anomalies and 30 `contextual` ones (a price typical of one region on an order from another). Only `quantity`, `unit_price` and `delivery_days` are scored.
- **sensor**: 1,440 hourly readings with a daily cycle and 150 anomalous points: 10 `point`, 8 `contextual` (daytime peak values at night), 24 `collective` (two 12-hour level shifts) and 108 `drift`.

`anomalyguard demo generate -d <dataset>` writes the same data with its ground truth (`demo generate` defaults to 1,000 rows for `orders`).

## Best per dataset

| Dataset | Best detector (F1) | Precision | Recall | F1 | ROC-AUC | Global `mad` F1 |
|---|---|---|---|---|---|---|
| tabular | `lof` | 0.81 | 0.88 | 0.84 | 0.975 | 0.65 |
| orders | `mad` by region | 0.81 | 1.00 | 0.90 | 1.000 | 0.63 |
| sensor | `ensemble[max](seasonal+cusum)` | 0.89 | 0.99 | 0.94 | 0.997 | 0.00 |

What the results show:

- Univariate detectors catch extreme values but cannot see broken correlations: on `tabular` they recall every point anomaly and almost no correlation anomalies. LOF and k-NN can see them.
- Global detectors miss contextual anomalies in grouped data. Detecting within each group (`mad by region`) recalls all of them.
- On a seasonal series, the seasonal residual catches point and contextual anomalies, and CUSUM catches sustained shifts and drift. Combined with `max`, they recover 99% of the anomalous points.
- Isolation Forest is the weakest on `tabular`: its axis-parallel splits fit strongly correlated features poorly.

## Reproduce the best configurations from the CLI

`demo generate` writes the same data as the benchmark (seed 42), and `--param` sets detector parameters:

```bash
anomalyguard demo generate -d tabular -n 2000 -o tabular.csv
anomalyguard detect tabular.csv -m lof
# P 0.81, R 0.88, F1 0.84

anomalyguard demo generate -d orders -n 2000 -o orders.csv
anomalyguard detect orders.csv -m mad --group-by region --columns quantity,unit_price,delivery_days
# P 0.81, R 1.00, F1 0.90

anomalyguard demo generate -d sensor -o sensor.csv
anomalyguard detect sensor.csv --columns temperature --time-column timestamp -m ensemble \
    --param 'ensemble.detectors=[{method: seasonal, period: 24}, {method: cusum, period: 24}]' \
    --param ensemble.combine=max
# P 0.89, R 0.99, F1 0.94
```

Scoring `detect -o report.json` against the `*_labels.csv` ground truth (counting the anomaly types listed for each dataset above) gives the numbers in the comments. For the sensor data, `-m seasonal,cusum --param cusum.period=24` (two detectors, combined with `any`) flags the same rows.

## Full output

Seed 42. Precision/recall/F1 at each detector's default threshold; ROC-AUC from raw scores.

### tabular (2000 rows, 100 anomalies)

| Detector | Precision | Recall | F1 | ROC-AUC | Recall: correlation | Recall: point | Time (s) |
|---|---|---|---|---|---|---|---|
| zscore | 0.85 | 0.50 | 0.63 | 0.804 | 0.00 | 1.00 | 0.00 |
| mad | 0.91 | 0.50 | 0.65 | 0.804 | 0.00 | 1.00 | 0.00 |
| iqr | 0.52 | 0.51 | 0.51 | 0.803 | 0.02 | 1.00 | 0.00 |
| grubbs | 1.00 | 0.50 | 0.67 | 0.804 | 0.00 | 1.00 | 0.01 |
| iforest | 0.24 | 0.27 | 0.26 | 0.828 | 0.00 | 0.54 | 0.14 |
| lof | 0.81 | 0.88 | 0.84 | 0.975 | 0.76 | 1.00 | 0.04 |
| knn | 0.92 | 0.70 | 0.80 | 0.959 | 0.40 | 1.00 | 0.02 |
| `ensemble[vote](mad+lof+knn)` | 0.92 | 0.70 | 0.80 | 0.937 | 0.40 | 1.00 | 0.06 |

### orders (2000 rows, 70 anomalies)

| Detector | Precision | Recall | F1 | ROC-AUC | Recall: contextual | Recall: point | Time (s) |
|---|---|---|---|---|---|---|---|
| zscore | 1.00 | 0.51 | 0.68 | 0.871 | 0.00 | 0.90 | 0.00 |
| mad | 0.71 | 0.57 | 0.63 | 0.943 | 0.00 | 1.00 | 0.00 |
| iqr | 0.45 | 0.60 | 0.52 | 0.899 | 0.07 | 1.00 | 0.00 |
| iforest | 0.66 | 0.60 | 0.63 | 0.922 | 0.07 | 1.00 | 0.16 |
| lof | 0.18 | 0.60 | 0.27 | 0.799 | 0.07 | 1.00 | 0.04 |
| mad by region | 0.81 | 1.00 | 0.90 | 1.000 | 1.00 | 1.00 | 0.01 |
| iqr by region | 0.50 | 1.00 | 0.66 | 1.000 | 1.00 | 1.00 | 0.01 |

### sensor (1440 rows, 150 anomalies)

| Detector | Precision | Recall | F1 | ROC-AUC | Recall: collective | Recall: contextual | Recall: drift | Recall: point | Time (s) |
|---|---|---|---|---|---|---|---|---|---|
| zscore | 1.00 | 0.01 | 0.01 | 0.595 | 0.00 | 0.00 | 0.00 | 0.10 | 0.00 |
| mad | 0.00 | 0.00 | 0.00 | 0.584 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| rolling_zscore(window=6) | 0.44 | 0.10 | 0.16 | 0.542 | 0.00 | 0.38 | 0.04 | 0.80 | 0.00 |
| ewma(span=3) | 0.47 | 0.13 | 0.20 | 0.560 | 0.04 | 0.62 | 0.04 | 0.90 | 0.01 |
| seasonal(period=24) | 1.00 | 0.23 | 0.37 | 0.657 | 0.67 | 1.00 | 0.00 | 1.00 | 0.00 |
| cusum(period=24) | 0.88 | 0.87 | 0.87 | 0.994 | 0.92 | 0.00 | 1.00 | 0.00 | 0.01 |
| iforest | 0.59 | 0.41 | 0.48 | 0.702 | 0.12 | 0.25 | 0.43 | 1.00 | 0.17 |
| `ensemble[max](seasonal+cusum)` | 0.89 | 0.99 | 0.94 | 0.997 | 0.96 | 1.00 | 1.00 | 1.00 | 0.01 |

### Data-quality checks (schema validation on `orders`)

| Issue | Injected | Caught | Recall |
|---|---|---|---|
| missing | 20 | 20 | 1.00 |
| type_error | 10 | 10 | 1.00 |
| duplicate | 20 | 20 | 1.00 |
