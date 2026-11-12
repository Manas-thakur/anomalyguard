"""Multivariate ML detectors implemented from scratch with NumPy.

* Isolation Forest (Liu, Ting & Zhou 2008) - random isolation trees.
* Local Outlier Factor (Breunig et al. 2000) - local density ratio.
* k-NN distance - mean distance to the k nearest neighbours.

Neighbour search uses ``scipy.spatial.cKDTree``; everything else (tree
growth, path lengths, reachability distances, LRD, LOF) is implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from anomalyguard.detect.base import Detector, fmt, robust_center_scale

EULER_GAMMA = 0.5772156649015329


def average_path_length(n: np.ndarray | int) -> np.ndarray:
    """c(n): average path length of an unsuccessful BST search over n points."""
    n = np.asarray(n, dtype=float)
    out = np.zeros_like(n)
    big = n > 2
    out[big] = 2.0 * (np.log(n[big] - 1.0) + EULER_GAMMA) - 2.0 * (n[big] - 1.0) / n[big]
    out[n == 2] = 1.0
    return out


class _MultivariateMixin:
    """Median imputation + robust scaling shared by the ML detectors."""

    def _prep_fit(self, X: np.ndarray) -> np.ndarray:
        self.center_, self.scale_ = robust_center_scale(X)
        return self._prep(X)

    def _prep(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.center_) / self.scale_
        return np.where(np.isfinite(Z), Z, 0.0)  # missing -> median

    def _auto_threshold(self, train_scores: np.ndarray) -> float:
        """Robust outlier cut-off on the training score distribution:
        ``median + k * 1.4826 * MAD`` (with a small floor on the spread)."""
        if len(train_scores) == 0:
            return self.default_threshold
        med = float(np.median(train_scores))
        mad = float(np.median(np.abs(train_scores - med))) * 1.4826
        spread = max(mad, 0.01 * abs(med), 1e-9)
        return max(med + self.auto_k * spread, getattr(self, "min_threshold", -np.inf))


@dataclass
class _Tree:
    feature: np.ndarray
    threshold: np.ndarray
    left: np.ndarray
    right: np.ndarray
    size: np.ndarray
    depth_limit: int


class IsolationForestDetector(_MultivariateMixin, Detector):
    """Isolation Forest. Score ``s = 2^(-E[h(x)] / c(psi))`` in (0, 1);
    anomalies are isolated in few splits and score close to 1."""

    name = "iforest"
    univariate = False
    default_threshold = 0.6
    description = "Isolation Forest: anomalies are isolated by fewer random splits."

    def __init__(
        self,
        n_estimators: int = 100,
        max_samples: int = 256,
        random_state: int | None = 42,
        auto_k: float = 4.0,
        min_threshold: float = 0.5,
        **kw,
    ):
        super().__init__(**kw)
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.random_state = random_state
        self.auto_k = auto_k
        self.min_threshold = min_threshold

    def _grow(self, X: np.ndarray, rng: np.random.Generator, limit: int) -> _Tree:
        feature: list[int] = []
        threshold: list[float] = []
        left: list[int] = []
        right: list[int] = []
        size: list[int] = []

        def grow(idx: np.ndarray, depth: int) -> int:
            node = len(feature)
            feature.append(-1)
            threshold.append(0.0)
            left.append(-1)
            right.append(-1)
            size.append(len(idx))
            if depth >= limit or len(idx) <= 1:
                return node
            sub = X[idx]
            lo, hi = sub.min(axis=0), sub.max(axis=0)
            candidates = np.flatnonzero(hi > lo)
            if len(candidates) == 0:
                return node
            f = int(rng.choice(candidates))
            split = float(rng.uniform(lo[f], hi[f]))
            mask = sub[:, f] < split
            feature[node] = f
            threshold[node] = split
            left[node] = grow(idx[mask], depth + 1)
            right[node] = grow(idx[~mask], depth + 1)
            return node

        grow(np.arange(len(X)), 0)
        return _Tree(
            np.array(feature),
            np.array(threshold),
            np.array(left),
            np.array(right),
            np.array(size),
            limit,
        )

    def _fit(self, X: np.ndarray) -> None:
        Z = self._prep_fit(X)
        n = len(Z)
        if n == 0:
            raise ValueError("Cannot fit on empty data")
        rng = np.random.default_rng(self.random_state)
        self.psi_ = int(min(self.max_samples, n))
        limit = int(np.ceil(np.log2(max(self.psi_, 2))))
        self.trees_ = [
            self._grow(Z[rng.choice(n, self.psi_, replace=False)], rng, limit)
            for _ in range(self.n_estimators)
        ]
        self.c_ = float(average_path_length(self.psi_)) or 1.0

    @staticmethod
    def _path_length(tree: _Tree, Z: np.ndarray) -> np.ndarray:
        node = np.zeros(len(Z), dtype=int)
        depth = np.zeros(len(Z))
        for _ in range(tree.depth_limit + 1):
            f = tree.feature[node]
            active = np.flatnonzero(f >= 0)
            if len(active) == 0:
                break
            nodes = node[active]
            go_left = Z[active, f[active]] < tree.threshold[nodes]
            node[active] = np.where(go_left, tree.left[nodes], tree.right[nodes])
            depth[active] += 1
        return depth + average_path_length(tree.size[node])

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        Z = self._prep(X)
        mean_path = np.mean([self._path_length(t, Z) for t in self.trees_], axis=0)
        return np.power(2.0, -mean_path / self.c_)

    def _explain(self, X, row, col, raw):
        return (
            f"isolation score {raw:.3f} > {self.effective_threshold:.3f}; "
            f"most unusual: {self._top_columns_text(X, row)}"
        )

    def get_params(self):
        return {
            **super().get_params(),
            "n_estimators": self.n_estimators,
            "max_samples": self.max_samples,
        }


class _NeighbourMixin(_MultivariateMixin):
    """Fits a KD-tree on the robust-scaled training data. When scoring the
    exact training matrix, each point's own entry is excluded (leave-one-out)."""

    def _fit_tree(self, X: np.ndarray) -> np.ndarray:
        Z = self._prep_fit(X)
        if len(Z) < 2:
            raise ValueError("Need at least 2 rows")
        self.k_ = int(min(self.n_neighbors, len(Z) - 1))
        self.train_ = Z
        self.tree_ = cKDTree(Z)
        return Z

    def _query(self, Z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        same = Z.shape == self.train_.shape and np.array_equal(Z, self.train_)
        k = self.k_ + 1 if same else self.k_
        dist, idx = self.tree_.query(Z, k=k)
        dist = dist.reshape(len(Z), -1)
        idx = idx.reshape(len(Z), -1)
        if same:
            # drop the self-match (the first neighbour equal to the point's own row)
            rows = np.arange(len(Z))[:, None]
            is_self = idx == rows
            no_self = ~is_self.any(axis=1)
            is_self[no_self, -1] = True  # duplicates: drop the farthest instead
            dist = dist[~is_self].reshape(len(Z), self.k_)
            idx = idx[~is_self].reshape(len(Z), self.k_)
        return dist, idx


class LOFDetector(_NeighbourMixin, Detector):
    """Local Outlier Factor: ratio of neighbours' local reachability density to
    the point's own. ~1 for inliers, >1 for points in sparser regions."""

    name = "lof"
    univariate = False
    default_threshold = 1.5
    description = "Local Outlier Factor: density relative to neighbours (local outliers)."

    def __init__(
        self, n_neighbors: int = 20, auto_k: float = 6.0, min_threshold: float = 1.2, **kw
    ):
        super().__init__(**kw)
        self.n_neighbors = n_neighbors
        self.auto_k = auto_k
        self.min_threshold = min_threshold

    def _fit(self, X: np.ndarray) -> None:
        Z = self._fit_tree(X)
        dist, idx = self._query(Z)
        self.kdist_ = dist[:, -1]
        reach = np.maximum(dist, self.kdist_[idx])
        self.lrd_ = 1.0 / (reach.mean(axis=1) + 1e-10)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        Z = self._prep(X)
        dist, idx = self._query(Z)
        reach = np.maximum(dist, self.kdist_[idx])
        lrd = 1.0 / (reach.mean(axis=1) + 1e-10)
        return self.lrd_[idx].mean(axis=1) / lrd

    def _explain(self, X, row, col, raw):
        return (
            f"local outlier factor {raw:.2f} > {self.effective_threshold:.2f} "
            f"(sparser than its {self.k_} neighbours); most unusual: {self._top_columns_text(X, row)}"
        )

    def get_params(self):
        return {**super().get_params(), "n_neighbors": self.n_neighbors}


class KNNDetector(_NeighbourMixin, Detector):
    """Mean distance to the k nearest neighbours in robust-scaled space."""

    name = "knn"
    univariate = False
    default_threshold = 3.0
    description = "Mean distance to the k nearest neighbours (global outliers)."

    def __init__(self, n_neighbors: int = 10, auto_k: float = 6.0, **kw):
        super().__init__(**kw)
        self.n_neighbors = n_neighbors
        self.auto_k = auto_k

    def _fit(self, X: np.ndarray) -> None:
        self._fit_tree(X)

    def _score_matrix(self, X: np.ndarray) -> np.ndarray:
        dist, _ = self._query(self._prep(X))
        return dist.mean(axis=1)

    def _explain(self, X, row, col, raw):
        return (
            f"mean distance to {self.k_} nearest neighbours {fmt(raw)} > "
            f"{fmt(self.effective_threshold)}; most unusual: {self._top_columns_text(X, row)}"
        )

    def get_params(self):
        return {**super().get_params(), "n_neighbors": self.n_neighbors}
