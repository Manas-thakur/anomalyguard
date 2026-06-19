# Part 4: `anomalyguard-remediate` — Data Remediation

## Purpose

Detection is only half the story. Once anomalies are detected, they need to be fixed (remediated). The remediate package provides strategies for automatically fixing common data quality issues — missing values, outliers, type errors, format inconsistencies — and flagging records that need human attention.

## Component Breakdown

### 4.1 Remediation Strategies

**File:** `anomalyguard/remediate/strategies.py`

```python
class RemediationStrategy(ABC):
    """Base class for remediation strategies."""
    
    name: str
    description: str
    
    @abstractmethod
    def can_remediate(self, field: Field, error: FieldError) -> bool: ...
    
    @abstractmethod
    def remediate(self, value: Any, field: Field, error: FieldError, context: RemediationContext) -> RemediationResult: ...
```

**`ImputationStrategy` — Fill Missing Values:**
```python
class ImputationStrategy(RemediationStrategy):
    """Fill missing or null values using various strategies."""
    
    def __init__(self, method: ImputationMethod = "auto"):
        self.method = method

class ImputationMethod(Enum):
    MEAN = "mean"                  # Column mean (numeric)
    MEDIAN = "median"              # Column median (numeric, robust)
    MODE = "mode"                  # Most frequent value (categorical)
    CONSTANT = "constant"          # User-specified constant
    FORWARD_FILL = "forward_fill"  # Last valid value (time-series)
    BACKWARD_FILL = "backward_fill"  # Next valid value (time-series)
    LINEAR_INTERPOLATION = "linear_interpolation"  # Linear between neighbors
    KNN = "knn"                    # K-nearest neighbors imputation
    MODEL = "model"                # ML model predicting missing value
    LLM = "llm"                    # LLM predicts reasonable value from context
    AUTO = "auto"                  # Automatically choose best method

class AutoImputer:
    """Automatically selects the best imputation method based on data characteristics."""
    
    def select_method(self, field: Field, stats: FieldStats) -> ImputationMethod:
        # If field is categorical → MODE
        if field.dtype in (DataType.CATEGORICAL, DataType.STRING):
            return ImputationMethod.MODE
        # If time-series data → FORWARD_FILL
        if stats.temporal_order_detected:
            return ImputationMethod.FORWARD_FILL
        # If outliers present → MEDIAN
        if stats.outlier_detected:
            return ImputationMethod.MEDIAN
        # Default → MEAN
        return ImputationMethod.MEAN
```

**`CappingStrategy` — Handle Outliers:**
```python
class CappingStrategy(RemediationStrategy):
    """Winsorize or cap extreme values."""
    
    def __init__(self, method: CappingMethod = "winsorize", lower_percentile=1, upper_percentile=99):
        ...
    
    def remediate(self, value, field, error, context):
        if self.method == CappingMethod.WINSORIZE:
            # Replace values below P1 with P1, above P99 with P99
            return min(max(value, self.lower_bound), self.upper_bound)
        elif self.method == CappingMethod.SOFT_CAP:
            # Pull towards median: new = median + sign(value - median) * cap_distance
            ...
        elif self.method == CappingMethod.DOMAIN_BOUNDS:
            # Apply min/max from domain knowledge
            return max(min(value, self.upper_bound), self.lower_bound)
```

**`TransformationStrategy` — Fix Format/Type Errors:**
```python
class TransformationStrategy(RemediationStrategy):
    """Fix type errors, format inconsistencies, and normalization issues."""
    
    strategies = {
        "type_coerce": TypeCoercionRemediator(),
        "date_normalize": DateNormalizer(),
        "case_normalize": CaseNormalizer(),
        "whitespace_clean": WhitespaceCleaner(),
        "currency_parse": CurrencyParser(),
        "phone_format": PhoneFormatter(),
        "unit_convert": UnitConverter(),
    }
```

**`FilteringStrategy` — Remove or Quarantine:**
```python
class FilteringStrategy(RemediationStrategy):
    """Remove anomalous records or quarantine them for review."""
    
    def __init__(self, action: FilterAction = "quarantine"):
        ...
```

### 4.2 Remediation Pipeline

**File:** `anomalyguard/remediate/pipeline.py`

```python
class RemediationPipeline:
    """Chain multiple remediation strategies with fallback."""
    
    def __init__(self, strategies: list[RemediationStrategy], fallback: str = "flag"):
        self.strategies = strategies
        self.fallback = fallback  # "flag", "drop", "keep_original"
    
    def remediate(self, record: Record, errors: dict[str, FieldError]) -> RemediatedRecord: ...
    
    def remediate_batch(self, records: list[Record], errors_list: list[dict[str, FieldError]]) -> list[RemediatedRecord]: ...

@dataclass
class RemediatedRecord:
    original: Record
    remediated: dict[str, Any]        # Remediated values
    changes: list[RemediationChange]  # What was changed and why
    fully_remediated: bool            # All errors fixed
    needs_human_review: bool          # Some issues couldn't be auto-fixed

@dataclass
class RemediationChange:
    field: str
    original_value: Any
    new_value: Any
    strategy: str                     # Which strategy fixed it
    confidence: float                 # Confidence in the fix (0.0-1.0)
```

### 4.3 LLM-Powered Remediation

**File:** `anomalyguard/remediate/llm.py`

For complex remediations where statistical methods aren't sufficient, use the local LLM to predict reasonable values.

```python
class LLMRemediator(RemediationStrategy):
    """Use local LLM to predict the correct value based on context.
    
    Example: If 'city' field is missing but 'zip_code' is present,
    the LLM can infer the city from the zip code.
    """
    
    def __init__(self, model_client, confidence_threshold=0.7):
        self.model = model_client
    
    async def remediate(self, value, field, error, context):
        prompt = self._build_prompt(value, field, error, context)
        response = await self.model.generate(prompt)
        # Parse structured response: {value, confidence, reasoning}
        ...
    
    def _build_prompt(self, value, field, error, context):
        return f"""You are a data cleaning assistant. A record has an anomalous value.
        
Field: {field.name}
Expected type: {field.dtype.value}
Error: {error.message}

Other fields in this record:
{json.dumps(context.record, indent=2)}

The current value '{value}' is anomalous. What should the correct value be?
Respond in JSON format:
{{"value": "corrected_value", "confidence": 0.95, "reasoning": "Because..."}}"""
```

### 4.4 Human Review Gate

**File:** `anomalyguard/remediate/human.py`

```python
class HumanReviewGate:
    """Pause for human review when automated remediation can't confidently fix an issue."""
    
    def __init__(self, notification: Notifier, timeout_hours=24):
        self.notifier = notification
        self.timeout = timeout_hours
    
    async def request_review(self, records: list[RemediatedRecord]) -> list[RemediatedRecord]:
        """Send records for human review and wait for decisions."""
        for record in records:
            await self.notifier.send(
                f"Anomaly needs review: {record.remediated}\n"
                f"Auto-fix attempted: {record.changes}\n"
                f"Accept / Edit / Reject"
            )
        # Wait for human decisions (polling or webhook)
        ...
```

### 4.5 Remediation Report

**File:** `anomalyguard/remediate/report.py`

```python
class RemediationReport:
    def __init__(self):
        self.results: list[RemediatedRecord] = []
    
    def summary(self) -> dict:
        return {
            "total_records": len(self.results),
            "fully_remediated": sum(1 for r in self.results if r.fully_remediated),
            "needs_human_review": sum(1 for r in self.results if r.needs_human_review),
            "changes_by_strategy": self._changes_by_strategy(),
            "changes_by_field": self._changes_by_field(),
            "confidence_distribution": self._confidence_distribution(),
        }
    
    def to_markdown(self) -> str:
        """Generate a remediation report in markdown."""
        ...
```

## Blog Content Angles

- "Auto-Fixing Bad Data: A Practical Guide to Data Remediation"
- "When to Impute vs When to Flag: Building Smart Remediation Pipelines"
- "Using Local LLMs for Context-Aware Data Cleaning"
- "The Remediation Report: Tracking What Was Fixed and Why"

## File Structure

```
packages/python/remediate/
├── __init__.py
├── strategies.py             # RemediationStrategy ABC + ImputationStrategy, CappingStrategy, TransformationStrategy, FilteringStrategy
├── pipeline.py               # RemediationPipeline, RemediatedRecord, RemediationChange
├── llm.py                    # LLMRemediator
├── human.py                  # HumanReviewGate
├── report.py                 # RemediationReport
└── errors.py                 # RemediationError
```
