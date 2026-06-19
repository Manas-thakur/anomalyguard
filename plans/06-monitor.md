# Part 6: `anomalyguard-monitor` — Monitoring Dashboard

## Purpose

The monitoring package collects metrics about the anomaly detection pipeline itself — anomaly rates, detector performance, data volume, latency — and provides a real-time dashboard for visualization. It also implements a feedback loop so the system improves over time.

## Component Breakdown

### 6.1 Metrics Collection

**File:** `anomalyguard/monitor/metrics.py`

```python
@dataclass
class PipelineMetrics:
    timestamp: datetime
    source: str                   # Source name
    records_processed: int
    records_with_anomalies: int
    anomaly_rate: float
    records_remediated: int
    remediation_success_rate: float
    alerts_sent: int
    pipeline_latency_ms: float
    detector_performance: dict[str, DetectorPerformance]  # Per-detector

@dataclass
class DetectorPerformance:
    name: str
    anomaly_count: int
    false_positive_count: int     # From feedback loop
    false_negative_count: int     # From feedback loop
    precision: float
    recall: float
    f1_score: float
    avg_latency_ms: float

class MetricsCollector:
    def __init__(self, storage: MetricsStorage):
        self.storage = storage
    
    def record(self, metrics: PipelineMetrics) -> None: ...
    def query(self, name: str, start: datetime, end: datetime) -> list[PipelineMetrics]: ...
```

### 6.2 Metrics Storage

**File:** `anomalyguard/monitor/storage.py`

```python
class MetricsStorage(ABC):
    @abstractmethod
    def store(self, metrics: PipelineMetrics) -> None: ...
    @abstractmethod
    def query_range(self, start: datetime, end: datetime, source: str | None = None) -> list[PipelineMetrics]: ...
    @abstractmethod
    def latest(self) -> PipelineMetrics | None: ...

class SQLiteMetricsStorage(MetricsStorage):
    """Local storage using SQLite (zero dependency)."""
    ...

class PostgreSQLMetricsStorage(MetricsStorage):
    """Cloud storage using PostgreSQL."""
    ...
```

### 6.3 Dashboard Backend (FastAPI)

**File:** `anomalyguard/monitor/api.py`

```python
# REST API for the React dashboard

GET  /api/v1/metrics/latest             # Current pipeline status
GET  /api/v1/metrics/history?range=24h  # Time-series data
GET  /api/v1/sources                    # List configured sources
GET  /api/v1/sources/{name}/status      # Source health + stats
GET  /api/v1/detectors                  # Detector performance comparison
GET  /api/v1/alerts/history             # Recent alerts
POST /api/v1/feedback                   # Submit feedback (false positive/negative)
```

### 6.4 Dashboard Frontend (React)

**File:** `anomalyguard/typescript/dashboard/`

**Pages:**
- **Overview**: Real-time anomaly rate gauge, pipeline health, recent alerts
- **Anomaly Explorer**: Browse detected anomalies, see details, submit feedback
- **Detector Performance**: Compare precision/recall across detectors, latency analysis
- **Trends**: Time-series charts of anomaly rates, data volume, remediation success
- **Configuration**: Manage sources, detectors, alert rules

**Key Components:**
- `AnomalyRateGauge`: Live gauge of current anomaly percentage
- `TimeSeriesChart`: Resizable zoomable time-series chart
- `AnomalyTable`: Sortable, filterable table of detected anomalies
- `DetectorComparisonChart`: Bar/radar chart comparing detector performance
- `FeedbackButton`: "This is not an anomaly" / "Missed anomaly" buttons

### 6.5 Feedback Loop

**File:** `anomalyguard/monitor/feedback.py`

```python
class FeedbackLoop:
    """Collect user feedback to improve detection over time."""
    
    def __init__(self, storage: FeedbackStorage, detector_update_callback=None):
        self.storage = storage
    
    async def record_feedback(self, feedback: AnomalyFeedback) -> None:
        """Record user feedback on a detection."""
        ...

    async def get_performance_metrics(self) -> dict[str, DetectorPerformance]:
        """Calculate precision/recall for each detector based on feedback."""
        ...

    async def auto_tune_thresholds(self) -> dict[str, float]:
        """Automatically adjust detector thresholds to optimize F1."""
        ...

@dataclass
class AnomalyFeedback:
    record_id: str
    detector_name: str
    was_anomaly: bool                # User's judgment
    user_action: str | None           # "accepted", "rejected", "corrected"
    comment: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

---

## File Structure

```
packages/python/monitor/
├── __init__.py
├── metrics.py                # PipelineMetrics, DetectorPerformance, MetricsCollector
├── storage.py                # MetricsStorage, SQLiteMetricsStorage, PostgreSQLMetricsStorage
├── api.py                    # FastAPI app for dashboard backend
├── feedback.py               # AnomalyFeedback, FeedbackLoop
└── dashboard.py              # Embedded dashboard (for local use, no React needed)

packages/typescript/dashboard/
├── package.json
├── src/
│   ├── App.tsx
│   ├── pages/
│   │   ├── Overview.tsx
│   │   ├── AnomalyExplorer.tsx
│   │   ├── DetectorPerformance.tsx
│   │   └── Configuration.tsx
│   └── components/
│       ├── AnomalyRateGauge.tsx
│       ├── TimeSeriesChart.tsx
│       └── FeedbackButton.tsx
```
