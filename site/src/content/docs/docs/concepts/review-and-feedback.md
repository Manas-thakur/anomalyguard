---
title: Review and feedback loop
description: The human review queue, applying approved values, and how feedback tunes detector thresholds.
---

## The review queue

Flagged values (from [remediation](/anomalyguard/docs/concepts/remediation/), confirmed [incidents](/anomalyguard/docs/concepts/incidents/), or an analysis's **Send to review**) go to a review queue stored in SQLite. Each item records the source (`pipeline`), the run, the row index, the column (empty for whole-row findings), the value, the reason, the detector, and an optional suggestion with a confidence.

Re-running a pipeline does not duplicate work: an item that is already pending for the same source, row, column and value is reused.

| Status | Meaning |
|---|---|
| `pending` | waiting for a decision |
| `approved` | a value to use was recorded: the value you entered, else the suggestion, else the original value |
| `rejected` | keep the original value |
| `applied` | the approved value was written into the analysis's cleaned file |

By default pipelines write to the queue in the monitor database (`.anomalyguard/anomalyguard.db`); `review.db` in a pipeline, or `fix --review-db`, picks another file. `review.enabled: false` turns it off for a pipeline.

### Working through it

- **Web app**: the [Review inbox](/anomalyguard/docs/guides/web-app/#review-inbox) is a keyboard-first split view with bulk actions.
- **CLI**: `anomalyguard review list`, `anomalyguard review approve ID [--value V]`, `anomalyguard review reject ID`. See the [CLI reference](/anomalyguard/docs/reference/cli/#review).
- **Python**: `ReviewQueue(path)` with `list`, `query`, `approve`, `reject` and `apply`.

### Applying decisions

Approving records the value to use; it does not edit any file by itself.

- For items from a web app **analysis**, **Apply** writes approved values into that analysis's cleaned CSV and marks the items `applied`.
- Items from **pipeline runs** stay `approved`. Write them into your data with `ReviewQueue.apply(df)`, which matches items by index label and column and returns the updated frame and the number of values written:

```python
from anomalyguard.remediate import ReviewQueue

queue = ReviewQueue(".anomalyguard/anomalyguard.db")
fixed, n = queue.apply(df, pipeline="orders_quality", mark=True)   # mark=True -> status 'applied'
```

## The feedback loop

Feedback is a label on a finding: **false positive** (it was normal) or **true positive** (it was a real problem). It is stored per detector in the monitor database. You give feedback by:

- **Mark as normal** (false positive) or **Confirm** (true positive) on an incident;
- **Mark as normal** (`m`) on a review item, which also rejects the item;
- `anomalyguard feedback fp --anomaly-id N` / `feedback tp --anomaly-id N` (or `--detector NAME`);
- `POST /api/feedback`.

### Tuning

`anomalyguard feedback tune`, **Tune from feedback** in Settings, or `POST /api/feedback/tune` adjusts a **threshold multiplier** per detector:

- Only feedback received since the detector was last tuned counts, and a detector needs **at least 3** new reviews.
- If precision over those reviews is **below 80%**, the multiplier rises by 15% (capped at 4.0), so the detector flags less.
- If precision is **95% or more** and the multiplier is above 1.0, it relaxes by the same step back toward 1.0.

Each tuning call moves a threshold by at most one step. The next pipeline run and every new analysis apply the multipliers. With `monitor.auto_tune: true`, a pipeline tunes after every run. Multipliers can also be set by hand (0.1 to 10) in Settings or with `PUT /api/thresholds/{detector}`.

```bash
anomalyguard feedback stats    # precision and multiplier per detector
anomalyguard feedback tune
```
