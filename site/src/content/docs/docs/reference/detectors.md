---
title: Detector reference
description: Every detector with what it does, its parameters and defaults, and when to use it.
---

All detectors live in `anomalyguard.detect`. In YAML, on the CLI and in `ag.detect()` they are referred to by name; in Python you can also construct the classes directly. [Detectors](/anomalyguard/docs/concepts/detectors/) explains scores, thresholds and combining.

## Common parameters

Every detector accepts these, in YAML specs and as constructor keywords:

| Parameter | Default | Meaning |
|---|---|---|
| `columns` | all numeric, non-id columns | Columns to score |
| `threshold` | per detector (below) | Raw-score threshold; overrides the default or automatic one |
| `contamination` | none | Flag this share of the training data (0 to 0.5): the threshold becomes the `1 - contamination` quantile of training scores |

Detector specs in YAML (and `ag.detect` / `run_detectors` dicts) also take:

| Key | Meaning |
|---|---|
| `method` (or `type`) | Detector name or alias |
| `group_by` | Wrap the detector in `grouped` with this column (or list of columns) |
| `min_group_size` | For `group_by`, default `20` |
| `params` | Constructor keywords as a mapping; they can also be given inline (`{method: iforest, n_estimators: 200}`) |

```yaml
detectors:
  - mad                                   # a name is enough
  - {method: iforest, n_estimators: 200, columns: [quantity, unit_price]}
  - {method: mad, columns: [unit_price], group_by: region}
  - {method: seasonal, columns: [temperature], period: 24}
  - {method: ensemble, detectors: [mad, lof, knn], combine: vote, min_votes: 2}
```

**Aliases**: `z`, `z_score` → `zscore`; `modified_zscore`, `robust_zscore` → `mad`; `tukey` → `iqr`; `isolation_forest`, `isolationforest` → `iforest`; `local_outlier_factor` → `lof`; `knn_distance` → `knn`; `rolling`, `moving_average` → `rolling_zscore`; `seasonal_decompose`, `stl` → `seasonal`; `changepoint`, `change_point` → `cusum`; `stuck`, `stuck_at`, `flat_line` → `flatline`. Names are case-insensitive and `-` works as `_`.

On the CLI, set any parameter with `--param DETECTOR.KEY=VALUE` (repeatable), for example `--param seasonal.period=168 --param rolling_zscore.window=48`. Values are read as YAML, so `--param 'ensemble.detectors=[{method: seasonal, period: 24}, cusum]'` works too.

## Statistical

Univariate: each column is scored on its own and findings name the column.

**Skewed columns.** Amounts, sizes and latencies are usually right-skewed: on their original scale the long upper tail is full of ordinary values that a symmetric rule flags (on clean log-normal data `mad` flagged 6.8% and `iqr` 10.2% of rows). With `log_scale: auto` (the default for all four statistical detectors), a column is scored on a log scale when it looks log-normal: at least 30 values, at most 1% of them zero or negative (those are then scored as far below the range), clearly right-skewed (`(q95 - q50) / (q50 - q5)` of at least 1.5) and close to symmetric on the log scale (the same ratio of the logs between 1/1.15 and 1.15). Small whole-number counts (median below 20) and columns with fewer than 10 distinct values stay on the original scale, and so does a mixture of differently scaled groups (prices in several currencies), which stays lopsided on the log scale and where a log scale would hide a price typed ×20; use `group_by` for those. Reasons then quote the median and fences on the original scale and say "log scale". With these rules the benchmark datasets are unaffected, while on clean log-normal data `mad` flags 0.1% and `iqr` 2.2% of rows. Set `log_scale: false` (CLI `--no-log-scale`) to always use the original scale, or `true` to force the log scale for positive columns. The `cap` remediation strategy uses the same rule for its fences.

### zscore

`ZScoreDetector`. Score `|x - mean| / std` per column. Default threshold **3.0**.

Fast and familiar, but the mean and standard deviation are inflated by the outliers themselves, so it under-detects on dirty data. Use it on roughly normal, mostly clean data.

### mad

`MADDetector`. Modified z-score `0.6745 × |x - median| / MAD` (Iglewicz and Hoaglin). Default threshold **3.5**. When more than half the values are identical (MAD = 0), it falls back to a scaled mean absolute deviation.

Robust to heavy contamination; the default choice for numeric columns. `bounds()` returns the fences used by the `cap` remediation strategy.

### iqr

`IQRDetector`. Tukey fences: the score is the distance outside `[Q1, Q3]` in IQR units, so the default threshold **1.5** reproduces `Q1 - 1.5 IQR` / `Q3 + 1.5 IQR`.

Simple and robust, but flags more than `mad` on skewed data.

### grubbs

`GrubbsDetector`. Iterative two-sided Grubbs test: during `fit` it repeatedly removes the most extreme value while it is significant, then scores values against the cleaned mean and standard deviation. The raw score is `G / G_critical`, so the threshold is **1.0**.

| Parameter | Default | Meaning |
|---|---|---|
| `alpha` | `0.05` | Significance level |
| `max_outlier_fraction` | `0.1` | At most this share of values is removed during fit |

Use it for small samples from a roughly normal distribution.

## Machine learning

Multivariate: each row is scored on all its columns together. Missing values are median-imputed and features are scaled robustly (median and IQR). Findings are per row; the reason names the most unusual columns. The threshold is set automatically from the training scores: median + `auto_k` × 1.4826 × MAD, with a floor of `min_threshold`.

### iforest

`IsolationForestDetector`. Isolation Forest: random isolation trees; anomalies are isolated by fewer splits. Score `2^(-E[h(x)] / c(n))`, in (0, 1).

| Parameter | Default | Meaning |
|---|---|---|
| `n_estimators` | `100` | Number of trees |
| `max_samples` | `256` | Sub-sample size per tree |
| `random_state` | `42` | Seed (`null` for random) |
| `auto_k` | `4.0` | Automatic threshold width |
| `min_threshold` | `0.5` | Lowest automatic threshold |

Good general-purpose detector for rows with an unusual combination of values. Axis-parallel splits fit strongly correlated features poorly; prefer `lof` or `knn` there.

### lof

`LOFDetector`. Local Outlier Factor: the ratio of the neighbours' local reachability density to the point's own. About 1 for inliers, above 1 in sparser regions. Uses a SciPy KD-tree for neighbour search.

| Parameter | Default | Meaning |
|---|---|---|
| `n_neighbors` | `20` | Neighbours (k) |
| `auto_k` | `6.0` | Automatic threshold width |
| `min_threshold` | `1.2` | Lowest automatic threshold |

Finds local outliers and broken correlations between features, even when every value is within its own normal range. Best on the `tabular` benchmark.

### knn

`KNNDetector`. Mean distance to the k nearest neighbours in robust-scaled space.

| Parameter | Default | Meaning |
|---|---|---|
| `n_neighbors` | `10` | Neighbours (k) |
| `auto_k` | `6.0` | Automatic threshold width |

Finds global outliers far from all other rows. Similar use to `lof`, and simpler.

## Time series

Univariate and order-dependent: rows must be in time order and evenly spaced. Pass `time_column` (CLI `--time-column`): rows are sorted by time and the time-series detectors run on a **regular time grid**. The grid step is the median spacing of the timestamps; when the series has gaps, the missing points are inserted as empty values (detectors skip or interpolate them and never report them) and a warning gives the number and size of the gaps, so `period` and `window` count clock time rather than rows. Without the grid, a 12-hour gap in hourly data would shift every later point by 12 hours of seasonal phase. The grid is not used (with a warning) when timestamps repeat (several series in one column: use `group_by`), are not evenly spaced, or are so sparse that the grid would be more than four times longer than the data. Findings name the column and give the expected value.

### rolling_zscore

`RollingZScoreDetector`. Deviation from a trailing window that excludes the current point. With `robust: true` the centre is the rolling median and the scale is the rolling IQR / 1.349, so earlier spikes do not mask later ones. A window whose scale collapses below half the series' typical window scale (for example while a sensor repeats one value) uses the typical scale instead, so normal readings after a stuck period are not flagged; use `flatline` to catch the stuck period itself. Default threshold **4.0**.

| Parameter | Default | Meaning |
|---|---|---|
| `window` | `24` | Trailing window length |
| `min_periods` | `max(3, window // 2)` | Points needed before scoring |
| `robust` | `true` | Median/IQR (`true`) or mean/std (`false`) |

Use a short window for spikes in series without a strong cycle.

### ewma

`EWMADetector`. Compares each value to an exponentially weighted moving average forecast made before it. Large residuals are clipped before the state updates, so a spike does not poison the baseline. Default threshold **4.0**.

| Parameter | Default | Meaning |
|---|---|---|
| `span` | `24` | EWMA span (`alpha = 2 / (span + 1)`) |
| `warmup` | `span` | Points used to initialise the forecast; earlier points are not scored |

Use for spikes in a slowly moving series.

### seasonal

`SeasonalResidualDetector`. Robust additive decomposition: trend is a centred rolling median, seasonality is the per-phase median of the detrended series. The residual is scored with a robust z-score. Default threshold **4.0**. Series shorter than two periods are scored with a plain robust z-score.

| Parameter | Default | Meaning |
|---|---|---|
| `period` | `24` | Samples per cycle (24 for hourly data with a daily cycle) |
| `trend_window` | `3 × period` | Window of the rolling-median trend |

Catches values that are normal overall but wrong for their place in the cycle, for example a daytime peak at 3 a.m. Pair it with `cusum` for sustained shifts.

### cusum

`CUSUMDetector`. Two-sided tabular CUSUM on robust-standardised values (clipped to ±4 so single spikes do not trigger it): `S+ = max(0, S+ + z - k)`, `S- = max(0, S- - z - k)`, flagged where `max(S+, S-) > h`. The statistic is capped at 1.5 h so alarms clear soon after a shift ends. Default threshold (h) **5.0**.

| Parameter | Default | Meaning |
|---|---|---|
| `k` | `1.0` | Slack: half the shift, in robust standard deviations, the chart is tuned to catch |
| `baseline` | all data | Use only the first N points as the reference level |
| `period` | none | Remove this seasonal profile before standardising |

Catches level shifts and drift. Best single detector for collective and drift anomalies on the `sensor` benchmark.

### flatline

`FlatlineDetector`. Stuck-at detection: the score of a point is the length of the run of identical consecutive values it belongs to, and runs longer than the threshold are flagged (every point of the run). By default the threshold is learned from the data: three times the 95th percentile of the column's run lengths, and at least `min_run`, so columns that legitimately repeat values (counts, rounded readings) are not flagged. A fixed `threshold` is a run length in points. Missing values break a run.

| Parameter | Default | Meaning |
|---|---|---|
| `min_run` | `5` | Smallest run length the learned threshold can have |
| `tolerance` | `0` | Values within this distance of the run's first value count as equal |

Catches a sensor or feed that keeps reporting its last value. On hourly IoT test data with a 30-hour stuck period it flagged all 30 stuck readings plus the reading they repeat, and nothing else.

## Wrappers

### grouped

`GroupedDetector(base, group_by, min_group_size=20)`. Fits a copy of `base` per value of `group_by` (one column or a list) and scores each row against its own group. Groups smaller than `min_group_size` use a detector fitted on all the data, and their reasons say `global baseline`. Scores are normalised, so the threshold is **1.0**. Name in results: `grouped(<base> by <columns>)`.

In YAML and on the CLI, use `group_by` on any detector spec (or `--group-by` / `detection.group_by` for all of them) rather than naming `grouped` directly.

### ensemble

`EnsembleDetector(detectors, method="mean", min_votes=None, weights=None, cap=5.0)`. Combines normalised scores of member detectors into one score with threshold **1.0**.

| Parameter (YAML key) | Default | Meaning |
|---|---|---|
| `detectors` | required | Member specs (names or mappings) |
| `combine` (`method` in Python) | `mean` | `mean`, `max`, `vote` or `weighted` |
| `min_votes` | majority (`len // 2 + 1`) | For `vote`: members that must flag the row |
| `weights` | equal | For `weighted`: one weight per member |
| `cap` | `5.0` | Each member's normalised score is capped at this before averaging |

`max` is equivalent to "any member fires" but yields one finding per row. On the `sensor` benchmark, `max` of `seasonal` and `cusum` recalls 99% of the anomalies.

## Python

```python
from anomalyguard.detect import (
    MADDetector, IsolationForestDetector, GroupedDetector, EnsembleDetector,
    build_detector, run_detectors,
)

det = MADDetector(columns=["unit_price"]).fit(df)
res = det.detect(df)           # DetectionResult: labels, scores, raw_scores, findings
res.findings[0].reason         # 'unit_price=2286 has modified z-score 53.2 vs median 47.46 (threshold 3.5)'

det = build_detector({"method": "ensemble", "detectors": ["mad", "lof", "knn"], "combine": "vote", "min_votes": 2})
report = run_detectors(df, [det, GroupedDetector(MADDetector(), group_by="region")])
```
