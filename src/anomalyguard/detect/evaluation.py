"""Detection quality metrics (no scikit-learn needed)."""

from __future__ import annotations

from typing import Any

import numpy as np


def confusion(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, int]:
    t = np.asarray(y_true).astype(bool)
    p = np.asarray(y_pred).astype(bool)
    return {
        "tp": int((t & p).sum()),
        "fp": int((~t & p).sum()),
        "fn": int((t & ~p).sum()),
        "tn": int((~t & ~p).sum()),
    }


def precision_recall_f1(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    c = confusion(y_true, y_pred)
    precision = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
    recall = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic (ties averaged)."""
    from scipy.stats import rankdata

    y = np.asarray(y_true).astype(bool)
    s = np.nan_to_num(np.asarray(scores, dtype=float), nan=0.0)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def evaluate(
    y_true: np.ndarray, y_pred: np.ndarray, scores: np.ndarray | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {**precision_recall_f1(y_true, y_pred), **confusion(y_true, y_pred)}
    if scores is not None:
        out["roc_auc"] = roc_auc(y_true, scores)
    return out
