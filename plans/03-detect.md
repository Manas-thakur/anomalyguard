# Part 3: `anomalyguard-detect` — Anomaly Detection

## Purpose

The detect package implements multiple anomaly detection algorithms — statistical, machine learning, time-series, and contextual — and combines them into ensemble detectors for robust results.

## Architecture

```
Detector Interface
├── Statistical Methods
│   ├── ZScoreDetector       — Detect outliers using z-score (distance from mean in std devs)
│   ├── IQRDetector          — Interquartile range method (robust to outliers)
│   ├── MADDetector          — Median Absolute Deviation (most robust)
│   ├── GrubbsTest           — Grubbs' test for single outlier (normal distribution)
│   └── CDFDetector          — Cumulative distribution function threshold
│
├── ML Methods
│   ├── IsolationForestDetector  — Ensemble of isolation trees
│   ├── OneClassSVMDetector      — Boundary-based anomaly detection
│   ├── LOFDetector              — Local Outlier Factor (density-based)
│   ├── AutoencoderDetector      — Neural network reconstruction error
│   ├── DBSCANDetector           — Density-based clustering outliers
│   └── GMMDetector              — Gaussian Mixture Model probability threshold
│
├── Time-Series Methods
│   ├── MovingAverageDetector    — Residuals from rolling window
│   ├── ExponentialSmoothingDetector — Holt-Winters residuals
│   ├── SeasonalDecomposeDetector — STL decomposition residuals
│   ├── ChangePointDetector      — CUSUM and PELT algorithms
│   └── ARIMADetector            — ARIMA forecast residuals
│
├── Contextual Methods
│   ├── GroupedDetector          — Anomalies within groups (per-customer, per-region)
│   ├── CrossFeatureDetector     — Unexpected feature interactions
│   └── LLMContextDetector       — LLM-based domain-specific plausibility
│
└── Ensemble Methods
    ├── VotingEnsemble           — Majority vote across detectors
    ├── WeightedEnsemble         — Weighted combination by detector performance
    └── StackingEnsemble         — Meta-detector that learns to combine
```

## Component Breakdown

### 3.1 Detector Interface

**File:** `anomalyguard/detect/base.py`

```python
class Detector(ABC):
    """Base class for all anomaly detectors."""
    
    name: str
    config: DetectorConfig
    
    @abstractmethod
    def fit(self, data: np.ndarray, fields: list[str] | None = None) -> None:
        """Fit the detector on training data (unsupervised)."""
    
    @abstractmethod
    def predict(self, data: np.ndarray) -> np.ndarray:
        """Return anomaly scores (higher = more anomalous)."""
    
    @abstractmethod
    def predict_labels(self, data: np.ndarray, threshold: float | None = None) -> np.ndarray:
        """Return binary labels: 1 = anomaly, 0 = normal."""

@dataclass
class DetectorConfig:
    threshold: float = 0.95      # Default anomaly threshold
    contamination: float = 0.1   # Expected proportion of anomalies (for automated threshold)
    random_seed: int = 42
    
@dataclass
class AnomalyResult:
    record_index: int
    field: str | None            # Which field is anomalous (or None for record-level)
    score: float
    is_anomaly: bool
    detector_name: str
    explanation: str | None = None
    details: dict | None = None
```

### 3.2 Statistical Methods

**File:** `anomalyguard/detect/statistical.py`

**ZScoreDetector:**
```python
class ZScoreDetector(Detector):
    """Detect anomalies using z-score (distance from mean in standard deviations).
    
    Anomaly = |z-score| > threshold (default 3, corresponding to ~0.3% for normal distribution)
    Works best for roughly normal distributions without extreme outliers.
    """
    
    def fit(self, data, fields=None):
        self.mean = np.nanmean(data, axis=0)
        self.std = np.nanstd(data, axis=0)
        # Handle zero std: replace with small epsilon
        self.std = np.where(self.std == 0, 1e-10, self.std)
    
    def predict(self, data):
        z_scores = np.abs((data - self.mean) / self.std)
        return z_scores / np.max(z_scores)  # Normalize to [0, 1]
```

**IQRDetector:**
```python
class IQRDetector(Detector):
    """Interquartile Range method. Robust to outliers in training data.
    
    Anomaly = value < Q1 - 1.5*IQR or value > Q3 + 1.5*IQR
    The 1.5 multiplier can be adjusted (1.5 = "mild", 3 = "extreme" outliers).
    """
    
    def fit(self, data, fields=None):
        self.q1 = np.nanpercentile(data, 25, axis=0)
        self.q3 = np.nanpercentile(data, 75, axis=0)
        self.upper = self.q3 + self.multiplier * self.iqr
        self.lower = self.q1 - self.multiplier * self.iqr
```

**MADDetector:**
```python
class MADDetector(Detector):
    """Median Absolute Deviation. Most robust to outliers.
    
    MAD = median(|xi - median(X)|)
    Anomaly = |xi - median(X)| / MAD > threshold (typically 3-5)
    """
    
    def fit(self, data, fields=None):
        self.median = np.nanmedian(data, axis=0)
        mad = np.nanmedian(np.abs(data - self.median), axis=0)
        self.mad = np.where(mad == 0, 1e-10, mad)
```

**Comparison of Statistical Methods:**

| Method | Robust to Outliers | Assumes Normal Dist | Best For |
|--------|-------------------|---------------------|----------|
| Z-Score | No | Yes | Clean datasets |
| IQR | Yes | No | General purpose, skewed data |
| MAD | Very | No | Data with many outliers |
| Grubbs | No | Yes | Testing for single outlier |

### 3.3 ML Methods

**File:** `anomalyguard/detect/ml.py`

**IsolationForestDetector:**
```python
class IsolationForestDetector(Detector):
    """Isolation Forest: ensemble of isolation trees.
    
    Anomalies are 'few and different' — easier to isolate (fewer splits).
    Score: path length to isolate the point (shorter = more anomalous).
    
    Implements from scratch:
    1. Randomly select a feature and split value
    2. Build tree until depth limit or single point
    3. Average path length across ensemble
    """
    
    def __init__(self, n_estimators=100, max_samples="auto", max_depth=10):
        self.trees = []
        ...
    
    def fit(self, data, fields=None):
        n_samples = min(data.shape[0], 256) if self.max_samples == "auto" else self.max_samples
        for _ in range(self.n_estimators):
            sample = data[np.random.choice(data.shape[0], n_samples, replace=False)]
            tree = self._build_isolation_tree(sample, depth=0)
            self.trees.append(tree)
    
    def _build_isolation_tree(self, data, depth):
        if depth >= self.max_depth or data.shape[0] <= 1:
            return LeafNode(size=data.shape[0])
        feature = np.random.randint(data.shape[1])
        split_min, split_max = data[:, feature].min(), data[:, feature].max()
        if split_min == split_max:
            return LeafNode(size=data.shape[0])
        split_value = np.random.uniform(split_min, split_max)
        left = data[data[:, feature] < split_value]
        right = data[data[:, feature] >= split_value]
        return InternalNode(
            feature=feature,
            split_value=split_value,
            left=self._build_isolation_tree(left, depth + 1),
            right=self._build_isolation_tree(right, depth + 1),
        )
```

**AutoencoderDetector:**
```python
class AutoencoderDetector(Detector):
    """Neural network trained to reconstruct normal data.
    Anomalies = high reconstruction error.
    
    Architecture: input → encoder → bottleneck → decoder → output
    Loss: MSE between input and reconstruction.
    """
    
    def __init__(self, hidden_dims=[64, 32, 16], learning_rate=0.001, epochs=50):
        self.encoder = ...  # Simple feedforward network
        self.decoder = ...
    
    def fit(self, data, fields=None):
        # Normalize data
        # Train autoencoder to reconstruct normal data
        # Loss = MSE(input, reconstruction)
        ...
    
    def predict(self, data):
        reconstructions = self.decoder(self.encoder(data))
        errors = np.mean((data - reconstructions) ** 2, axis=1)
        return errors / np.max(errors)  # Normalize to [0, 1]
```

### 3.4 Time-Series Methods

**File:** `anomalyguard/detect/timeseries.py`

**MovingAverageDetector:**
```python
class MovingAverageDetector(Detector):
    """Detect anomalies as deviations from rolling window statistics.
    
    Anomaly = |value - window_mean| > threshold * window_std
    """
    
    def __init__(self, window_size=30, threshold=3.0):
        self.window_size = window_size
        self.threshold = threshold
    
    def predict(self, data):
        # data is 1D time series
        anomalies = np.zeros_like(data, dtype=float)
        for i in range(self.window_size, len(data)):
            window = data[i - self.window_size : i]
            mean = np.mean(window)
            std = np.std(window)
            if std > 0:
                z = abs(data[i] - mean) / std
                anomalies[i] = z / self.threshold  # Normalize
        return anomalies
```

**ChangePointDetector (CUSUM):**
```python
class CUSUMDetector(Detector):
    """Cumulative Sum control chart for detecting change points.
    
    Maintains upper and lower cumulative sums:
    S_high[i] = max(0, S_high[i-1] + x[i] - mean - drift)
    S_low[i] = max(0, S_low[i-1] - x[i] + mean - drift)
    Change point when either exceeds threshold.
    """
    
    def __init__(self, drift=0.01, threshold=5.0):
        self.drift = drift
        self.threshold = threshold
```

**SeasonalDecomposeDetector:**
```python
class SeasonalDecomposeDetector(Detector):
    """STL (Seasonal-Trend decomposition using LOESS) residuals.
    
    Decompose: time_series = trend + seasonal + residual
    Detect anomalies in the residual component.
    """
    
    def __init__(self, period=24, seasonal=7):
        self.period = period  # E.g., 24 for hourly data with daily seasonality
    
    def fit(self, data, fields=None):
        # 1. Estimate trend (moving average with period window)
        # 2. Detrend: data - trend
        # 3. Estimate seasonal: average of detrended values at each period position
        # 4. Residual: data - trend - seasonal
        # Store seasonal component
        ...
```

### 3.5 Contextual Methods

**File:** `anomalyguard/detect/contextual.py`

**GroupedDetector:**
```python
class GroupedDetector(Detector):
    """Detect anomalies within groups (e.g., per-customer anomalies).
    
    A value might be normal globally but anomalous for a specific group.
    Example: $500 transaction is normal overall, but anomalous for a customer
    whose average transaction is $25.
    """
    
    def __init__(self, group_column: str, base_detector: Detector):
        self.group_column = group_column
        self.base_detector = base_detector
        self.group_detectors: dict[str, Detector] = {}
    
    def fit(self, data, fields=None):
        groups = self._split_by_group(data)
        for group_name, group_data in groups.items():
            detector = copy.deepcopy(self.base_detector)
            detector.fit(group_data)
            self.group_detectors[group_name] = detector
```

**CrossFeatureDetector:**
```python
class CrossFeatureDetector(Detector):
    """Detect unexpected interactions between features.
    
    Example: age=5 and income=$100,000 — each normal alone, but unusual together.
    
    Uses pairwise density estimation or association rule mining.
    """
    
    def __init__(self, method: Literal["pairwise_density", "association_rules"] = "pairwise_density"):
        self.pairwise_densities = {}  # (field_i, field_j) → density estimator
```

**LLMContextDetector:**
```python
class LLMContextDetector(Detector):
    """Use local LLM to evaluate domain-specific plausibility.
    
    For each record, prompt the LLM:
    "Is this data point plausible for a {domain} dataset? 
     Record: {record}
     Explain if anything seems anomalous."
    
    Returns: anomaly score based on LLM judgment.
    """
    
    def __init__(self, model_client, domain_description: str, batch_size=10):
        self.model = model_client
        self.domain = domain_description
```

### 3.6 Ensemble Methods

**File:** `anomalyguard/detect/ensemble.py`

```python
class VotingEnsemble(EnsembleDetector):
    """Majority vote across detectors."""
    
    def predict(self, data):
        predictions = np.array([d.predict(data) > d.config.threshold for d in self.detectors])
        votes = np.mean(predictions, axis=0)  # Fraction voting "anomaly"
        return votes

class WeightedEnsemble(EnsembleDetector):
    """Weighted combination based on individual detector performance."""
    
    def __init__(self, detectors: list[Detector], weights: list[float] | None = None):
        self.detectors = detectors
        self.weights = weights or [1.0] * len(detectors)
    
    def predict(self, data):
        scores = np.array([d.predict(data) for d in self.detectors])
        weighted = np.average(scores, axis=0, weights=self.weights)
        return weighted

class StackingEnsemble(EnsembleDetector):
    """Meta-detector trained on detector outputs."""
    
    def __init__(self, detectors: list[Detector], meta_detector: Detector):
        self.detectors = detectors
        self.meta_detector = meta_detector
    
    def fit(self, data, fields=None):
        # Train base detectors
        for d in self.detectors:
            d.fit(data)
        # Generate features for meta-detector
        meta_features = self._generate_meta_features(data)
        # Train meta-detector
        self.meta_detector.fit(meta_features)
```

## Blog Content Angles

- "Anomaly Detection Algorithms: From Z-Score to Isolation Forest — A Complete Guide"
- "Building Isolation Forest from Scratch in Python"
- "Time-Series Anomaly Detection: Moving Average, STL Decomposition, and CUSUM"
- "Contextual Anomalies: Why 'Global Normal, Local Anomaly' Matters"
- "Ensemble Detection: Combining Statistical and ML Methods for Robust Results"

## File Structure

```
packages/python/detect/
├── __init__.py
├── base.py                   # Detector ABC, DetectorConfig, AnomalyResult
├── statistical.py            # ZScoreDetector, IQRDetector, MADDetector, GrubbsTest
├── ml.py                     # IsolationForestDetector, OneClassSVMDetector, LOFDetector, AutoencoderDetector, DBSCANDetector, GMMDetector
├── timeseries.py             # MovingAverageDetector, ExponentialSmoothingDetector, SeasonalDecomposeDetector, ChangePointDetector, ARIMADetector
├── contextual.py             # GroupedDetector, CrossFeatureDetector, LLMContextDetector
├── ensemble.py               # VotingEnsemble, WeightedEnsemble, StackingEnsemble
├── threshold.py              # Threshold optimization (using validation data to find best threshold)
├── evaluation.py             # Precision, recall, F1 for detector evaluation
└── errors.py                 # DetectorNotFittedError, InvalidDataError
```
