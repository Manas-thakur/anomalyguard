# Part 7: `anomalyguard-pipeline` — Pipeline Orchestration

## Purpose

The pipeline package ties everything together — ingest → schema → detect → remediate → alert → monitor — into configurable, schedulable pipelines. It manages pipeline state, supports checkpointing, and provides pipeline templates for common use cases.

## Component Breakdown

### 7.1 Pipeline Definition

**File:** `anomalyguard/pipeline/definition.py`

```python
@dataclass
class PipelineConfig:
    name: str
    description: str
    source: SourceConfig
    schema_config: SchemaConfig
    detectors: list[DetectorConfig]
    remediators: list[RemediatorConfig]
    notifiers: list[NotifierConfig]
    schedule: ScheduleConfig | None = None  # Cron expression
    alert_rules: list[AlertRuleConfig] = field(default_factory=list)
    enabled: bool = True
```

Pipelines are defined in YAML:

```yaml
name: "ecommerce_orders_quality"
description: "Monitor e-commerce order data for anomalies"
source:
  type: csv
  path: "./data/orders.csv"
  delimiter: ","
  has_header: true
schema_config:
  infer: true
  strict: false
detectors:
  - type: zscore
    threshold: 3.0
    fields: ["price", "quantity"]
  - type: isolation_forest
    contamination: 0.05
    n_estimators: 100
remediators:
  - type: imputation
    method: median
    fields: ["quantity"]
  - type: capping
    method: winsorize
    percentiles: [1, 99]
    fields: ["price"]
  - type: filter
    action: quarantine
    on: "critical"
notifiers:
  - type: console
    severity: warning
  - type: slack
    webhook_url: "https://hooks.slack.com/..."
    severity: error
schedule:
  cron: "0 */6 * * *"  # Every 6 hours
alert_rules:
  - type: threshold
    metric: anomaly_rate
    threshold: 0.1
    window: 1h
```

### 7.2 Pipeline Executor

**File:** `anomalyguard/pipeline/executor.py`

```python
class PipelineExecutor:
    def __init__(self, config: PipelineConfig):
        self.config = config
    
    async def run(self) -> PipelineResult:
        """Execute one full pipeline run."""
        
        # 1. Connect to source
        source = self._create_source(self.config.source)
        await source.connect()
        
        # 2. Infer or load schema
        if self.config.schema_config.infer:
            sample = [r async for r in source.read(batch_size=1000)]
            schema = SchemaInferenceEngine().infer(sample)
        else:
            schema = await self._load_schema()
        
        # 3. Process records in batches
        results = []
        async for batch in source.read(batch_size=10000):
            # Validate schema
            validation = SchemaValidator(schema).validate_batch(batch)
            
            # Detect anomalies
            anomalies = self._detect_anomalies(batch, validation)
            
            # Remediate
            remediated = self._remediate(batch, anomalies)
            
            # Alert
            alerts = await self._alert(anomalies, remediated)
            
            results.append(BatchResult(batch, validation, anomalies, remediated, alerts))
        
        # 4. Update metrics
        metrics = self._compute_metrics(results)
        await self._store_metrics(metrics)
        
        # 5. Save checkpoint
        await source.checkpoint()
        await source.disconnect()
        
        return PipelineResult(
            config=self.config,
            results=results,
            metrics=metrics,
            status="success",
        )
```

### 7.3 Scheduling

**File:** `anomalyguard/pipeline/scheduler.py`

```python
class PipelineScheduler:
    """Schedule pipeline runs using cron expressions."""
    
    def __init__(self, pipelines: list[PipelineConfig]):
        self.pipelines = pipelines
        self.active_tasks: dict[str, asyncio.Task] = {}
    
    async def start(self):
        for pipeline in self.pipelines:
            if pipeline.schedule:
                task = asyncio.create_task(self._run_scheduled(pipeline))
                self.active_tasks[pipeline.name] = task
    
    async def _run_scheduled(self, pipeline: PipelineConfig):
        cron = croniter(pipeline.schedule.cron, datetime.utcnow())
        while True:
            next_run = cron.get_next(datetime)
            await asyncio.sleep((next_run - datetime.utcnow()).total_seconds())
            executor = PipelineExecutor(pipeline)
            await executor.run()
```

### 7.4 Pipeline Templates

**File:** `anomalyguard/pipeline/templates.py`

**Pre-built pipeline templates:**

```python
PIPELINE_TEMPLATES = {
    "csv_quality_scan": PipelineConfig(
        name="csv_quality_scan",
        description="Scan CSV files for common data quality issues",
        source=SourceConfig(type="csv"),
        detectors=[
            DetectorConfig(type="zscore", threshold=3.0),
            DetectorConfig(type="iqr"),
        ],
        remediators=[
            RemediatorConfig(type="imputation", method="median"),
            RemediatorConfig(type="capping", method="winsorize"),
        ],
        notifiers=[
            NotifierConfig(type="console", severity="info"),
        ],
    ),
    "timeseries_monitor": PipelineConfig(
        # Real-time time-series anomaly detection
        ...
    ),
    "database_quality": PipelineConfig(
        # Schema validation + anomaly detection on DB tables
        ...
    ),
}
```

### 7.5 State Management

**File:** `anomalyguard/pipeline/state.py`

```python
class PipelineStateManager:
    """Manages pipeline state: checkpoints, run history, errors."""
    
    def save_checkpoint(self, pipeline_name: str, checkpoint: Checkpoint) -> None: ...
    def get_checkpoint(self, pipeline_name: str) -> Checkpoint | None: ...
    def get_run_history(self, pipeline_name: str, limit: int = 10) -> list[RunRecord]: ...
    def get_error_log(self, pipeline_name: str) -> list[ErrorRecord]: ...
```

---

## File Structure

```
packages/python/pipeline/
├── __init__.py
├── definition.py             # PipelineConfig, SourceConfig, DetectorConfig, etc.
├── executor.py               # PipelineExecutor, PipelineResult, BatchResult
├── scheduler.py              # PipelineScheduler (cron-based)
├── templates.py              # Built-in pipeline templates
├── state.py                  # PipelineStateManager
└── errors.py                 # PipelineError
```
