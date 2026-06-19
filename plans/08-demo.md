# Part 8: `anomalyguard-demo` — Demo & Benchmark Suite

## Purpose

The demo package provides synthetic data generators, known-ground-truth datasets, and a comprehensive benchmark suite for evaluating anomaly detection performance.

## Component Breakdown

### 8.1 Synthetic Data Generator

**File:** `anomalyguard/demo/generator.py`

```python
class SyntheticDataGenerator:
    """Generate synthetic datasets with configurable anomaly injection."""
    
    def generate_tabular(
        self,
        n_rows: int = 10000,
        n_features: int = 10,
        anomaly_rate: float = 0.05,
        distributions: list[str] | None = None,  # "normal", "uniform", "exponential"
        seed: int = 42,
    ) -> tuple[pd.DataFrame, np.ndarray]:
        """Generate tabular data with injected anomalies.
        
        Returns: (data, ground_truth_labels)
        ground_truth_labels[i] = 1 if row i is an anomaly
        """
        rng = np.random.RandomState(seed)
        n_anomalies = int(n_rows * anomaly_rate)
        
        # Generate normal data
        data = self._generate_normal(n_rows, n_features, distributions, rng)
        
        # Inject anomalies
        anomaly_indices = rng.choice(n_rows, n_anomalies, replace=False)
        data[anomaly_indices] = self._generate_anomalies(n_anomalies, n_features, distributions, rng)
        
        labels = np.zeros(n_rows)
        labels[anomaly_indices] = 1
        
        return pd.DataFrame(data, columns=[f"feature_{i}" for i in range(n_features)]), labels
    
    def generate_timeseries(
        self,
        n_points: int = 10000,
        trend: bool = True,
        seasonality: bool = True,
        noise_level: float = 0.1,
        anomaly_types: list[str] = ["point", "contextual", "collective"],
        anomaly_rate: float = 0.05,
        seed: int = 42,
    ) -> tuple[pd.Series, np.ndarray]:
        """Generate time series data with injected anomalies.
        
        anomaly_types:
        - "point": single extreme value
        - "contextual": value normal globally but anomalous for time of day
        - "collective": a sequence of values that together are anomalous
        - "change_point": sudden shift in mean/variance
        """
        ...
```

**Anomaly Types Injected:**

| Type | Example | Detection Difficulty |
|------|---------|---------------------|
| Point outlier | `value = mean + 10*std` | Easy |
| Contextual outlier | Normal value at wrong time | Medium |
| Collective anomaly | Subsequence with unusual pattern | Medium |
| Change point | Sudden mean shift | Hard |
| Missing data gap | Block of NaN values | Easy |
| Drift | Gradual distribution shift | Hard |
| Duplicate | Exact duplicate rows | Easy |
| Type error | String in numeric column | Easy |

### 8.2 Demo Datasets

**File:** `anomalyguard/demo/datasets.py`

Pre-configured datasets for demonstration:

| Dataset | Description | Source |
|---------|-------------|--------|
| `ecommerce_orders` | Order records with price/quantity outliers, missing customer IDs, date inconsistencies | Synthetic |
| `sensor_readings` | IoT sensor data with temperature spikes, sensor drift, communication gaps | Synthetic |
| `financial_transactions` | Transaction amounts with outliers, currency mismatches, duplicates | Synthetic |
| `server_logs` | Log data with malformed entries, rate anomalies, error spikes | Synthetic |
| `network_traffic` | Network packets with DDoS patterns, port scan anomalies | Synthetic |

### 8.3 Benchmark Suite

**File:** `anomalyguard/demo/benchmark.py`

```python
class BenchmarkSuite:
    """Compare all detectors against ground-truth datasets."""
    
    def __init__(self, datasets: list[BenchmarkDataset], detectors: list[Detector]):
        self.datasets = datasets
        self.detectors = detectors
    
    async def run(self) -> BenchmarkReport:
        """Run all detectors against all datasets, collect metrics."""
        results = []
        for dataset in self.datasets:
            data, labels = dataset.load()
            for detector in self.detectors:
                detector.fit(data)
                predictions = detector.predict_labels(data)
                
                metrics = compute_detection_metrics(labels, predictions)
                results.append(BenchmarkResult(
                    dataset_name=dataset.name,
                    detector_name=detector.name,
                    metrics=metrics,
                    latency_ms=...,  # Measure fit + predict time
                ))
        
        return BenchmarkReport(results=results)
    
    def summary_markdown(self) -> str:
        """Generate benchmark report in markdown."""
        ...

@dataclass
class BenchmarkMetrics:
    precision: float
    recall: float
    f1_score: float
    accuracy: float
    auc_roc: float
    detection_delay: float | None     # For time-series: avg delay in detecting anomaly onset
    false_positive_rate: float
    false_negative_rate: float
    fit_time_ms: float
    predict_time_ms: float
    memory_usage_mb: float
```

### 8.4 CLI Demo

```bash
# Generate synthetic data
anomalyguard demo generate --type tabular --rows 10000 --anomaly-rate 0.05 --output data.csv

# Run benchmark
anomalyguard demo benchmark --datasets tabular,timeseries --detectors zscore,isolation_forest

# Show dataset
anomalyguard demo show --dataset ecommerce_orders --head 20 --anomalies
```

---

## File Structure

```
apps/demo/
├── __init__.py
├── generator.py              # SyntheticDataGenerator
├── datasets.py               # Benchmark datasets
├── benchmark.py              # BenchmarkSuite, BenchmarkReport, BenchmarkMetrics
├── evaluate.py               # Evaluation metrics (precision, recall, F1, etc.)
├── visualization.py          # Plot results (matplotlib/plotly)
└── notebooks/
    ├── quickstart.ipynb
    └── benchmark_results.ipynb
```
