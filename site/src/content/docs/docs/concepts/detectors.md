---
title: Detectors
description: How detectors work, how scores are normalised, and how to choose and combine them.
---

A **detector** learns what normal looks like from the data and scores every row. AnomalyGuard has eleven detectors in four families plus two wrappers (`grouped` and `ensemble`). `anomalyguard detectors` lists them; the [Detector reference](/anomalyguard/docs/reference/detectors/) has every parameter.

| Family | Detectors | Finds |
|---|---|---|
| Statistical (univariate) | `zscore`, `mad`, `iqr`, `grubbs` | extreme values in one column |
| Machine learning (multivariate) | `iforest`, `lof`, `knn` | rows whose combination of values is unusual |
| Time series (univariate, ordered) | `rolling_zscore`, `ewma`, `seasonal`, `cusum`, `flatline` | spikes, values wrong for their place in a cycle, level shifts and drift, stuck (repeated) values |
| Contextual | `grouped` | values unusual for their group (region, customer, sensor) |
| Ensemble | `ensemble` | combinations of the above |

## One interface

Every detector has the same methods: `fit(df)`, `score(df)`, `predict(df)` and `detect(df)`. `detect` returns labels, scores and **findings**: one per flagged cell (univariate detectors) or row (multivariate detectors), each with the detector name, the column, the value, a normalised score and a reason:

```
[region=east] unit_price=3035 has modified z-score 330.7 vs median 89.08 (threshold 3.5)
local outlier factor 137.86 > 1.28 (sparser than its 20 neighbours); most unusual: quantity=493 (robust z 329.8), delivery_days=5 (robust z 0.7)
quantity=493 fails Grubbs test (G=283.39 > critical 4.04, alpha=0.05)
```

Multivariate detectors cannot point at one column, so they name the most unusual columns (robust z of each value) in the reason, and attribute the finding to a column only when one stands out clearly.

By default a detector scores every numeric column that is not id-like. Pass `columns` to choose.

## Normalised scores

Every raw score is divided by the detector's threshold, so a **normalised score above 1.0 always means anomalous**, whichever detector produced it. That is what makes scores comparable across detectors and lets ensembles combine them. The web app and the stored findings use the same scale for severity: **high** at 3.0 and above, **medium** from 1.5, **low** below that.

## Thresholds

- **Fixed defaults.** Statistical and time-series detectors use textbook cut-offs: 3.0 for z-score, 3.5 for MAD (Iglewicz and Hoaglin), 1.5 IQR for Tukey fences, alpha 0.05 for Grubbs, 4.0 for the time-series residuals, h = 5 for CUSUM.
- **Automatic for ML detectors.** `iforest`, `lof` and `knn` set their threshold from the distribution of their own training scores: median + k × 1.4826 × MAD (k = 4 for Isolation Forest with a floor of 0.5, k = 6 for LOF with a floor of 1.2, k = 6 for k-NN).
- **`threshold`** overrides the raw threshold for any detector.
- **`contamination`** (between 0 and 0.5) flags a fixed share of the data instead: the threshold becomes the `1 - contamination` quantile of the training scores.
- **Feedback multipliers.** The [feedback loop](/anomalyguard/docs/concepts/review-and-feedback/) keeps a multiplier per detector (1.0 by default) that scales its threshold in later pipeline runs and analyses.
- **Sensitivity** in the web app scales every threshold: `low` × 1.5, `medium` × 1.0, `high` × 0.7.

## Combining detectors

Running several detectors produces one report. `combine` decides when a row counts as anomalous:

- `any` (default): at least one detector flagged it.
- `vote`: at least `min_votes` detectors flagged it.
- `all`: every detector flagged it.

`min_votes` defaults to 2 on the CLI (`--min-votes`) and in web app analyses, and to 1 in pipelines (set `detection.min_votes`). The report's row score is the highest normalised score across detectors.

The `ensemble` detector combines scores *inside* one detector instead: `mean` or `weighted` average of normalised scores (each capped at 5), `max`, or `vote` with `min_votes`. Use it when you want one combined finding rather than one per detector.

## Contextual detection

A unit price of 900 can be ordinary in one region and extreme in another. A global detector sees the overall spread and misses it. `group_by` wraps any detector in `grouped`, which fits a separate copy per group value and scores each row against its own group. Groups smaller than `min_group_size` (default 20) fall back to a detector fitted on all the data, and the reason says so (`[region=west, global baseline]`).

```bash
anomalyguard detect orders.csv -m mad --group-by region
```

On the benchmark `orders` data, `mad` by region recalls all 30 contextual anomalies; global `mad` recalls none. See [Benchmarks](/anomalyguard/docs/benchmarks/).

## Choosing detectors

| Data | Start with |
|---|---|
| Independent rows, a few numeric columns | `mad` (robust to the outliers it is looking for), plus `iforest` for odd combinations |
| Values that depend on a category | any detector with `group_by` |
| Correlated features where each value is in range but the combination is not | `lof` or `knn` |
| An hourly or daily series with a cycle | `seasonal` with `period` set to the cycle length, plus `cusum` for shifts and drift |
| A series without a cycle | `rolling_zscore` or `ewma` with a short window, plus `cusum` |
| A sensor or feed that can freeze | add `flatline` (runs of identical values) |
| Small samples from a roughly normal distribution | `grubbs` |

Time-series detectors expect rows in time order and evenly spaced. Pass `--time-column` (CLI), `time_column` (Python, analyses) or `detection.time_column` (pipelines): rows are sorted by time, and time-series detectors run on a regular grid where gaps in the timestamps become empty points (with a warning), so a missing day does not shift the seasonal phase. Findings are mapped back to the original row order. See [time series](/anomalyguard/docs/reference/detectors/#time-series).

Log-normal-like columns (positive, right-skewed amounts or latencies) are scored on a log scale by the statistical detectors, so their long upper tail is not flagged wholesale; see [skewed columns](/anomalyguard/docs/reference/detectors/#statistical).

`zscore` and `iqr` are fast but less robust: outliers inflate the mean and standard deviation that `zscore` measures against, so it under-detects on dirty data.
