# Part 2: `anomalyguard-schema` — Schema Validation & Data Quality

## Purpose

The schema package validates incoming data against expected types, constraints, and quality rules. It tracks data quality metrics over time and provides the foundation that anomaly detection builds upon.

## Component Breakdown

### 2.1 Schema Registry

**File:** `anomalyguard/schema/registry.py`

```python
@dataclass
class Schema:
    name: str
    fields: dict[str, Field]
    version: int
    created_at: datetime
    constraints: list[SchemaConstraint]

@dataclass
class Field:
    name: str
    dtype: DataType
    nullable: bool
    default: Any | None = None
    constraints: list[Constraint] = field(default_factory=list)
    description: str | None = None

class DataType(Enum):
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    CATEGORICAL = "categorical"
    JSON = "json"
    UNKNOWN = "unknown"

@dataclass
class Constraint:
    type: ConstraintType
    value: Any

class ConstraintType(Enum):
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    MIN = "min"
    MAX = "max"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    REGEX = "regex"
    ENUM = "enum"             # Set of allowed values
    FOREIGN_KEY = "foreign_key"
    CUSTOM = "custom"
```

### 2.2 Schema Validator

**File:** `anomalyguard/schema/validator.py`

Validates records against the schema, producing detailed validation reports.

```python
class SchemaValidator:
    def __init__(self, schema: Schema, strict: bool = True):
        self.schema = schema
        self.strict = strict  # If False, warn instead of fail on unknown fields
    
    def validate_record(self, record: Record) -> ValidationResult: ...
    def validate_batch(self, records: list[Record]) -> list[ValidationResult]: ...

@dataclass
class ValidationResult:
    record_index: int
    passed: bool
    field_errors: dict[str, FieldError]  # field_name → error
    warnings: list[str]

@dataclass
class FieldError:
    field: str
    constraint: ConstraintType
    expected: Any
    actual: Any
    message: str
```

**Validation Rules:**
- Type check: value is coercible to declared type
- Null check: if not nullable, value must not be null
- Range check: numeric values within [min, max]
- Length check: string values within [min_length, max_length]
- Regex check: string matches pattern
- Enum check: value is in allowed set
- Unique check: value is unique within batch (configurable)

### 2.3 Type Coercion

**File:** `anomalyguard/schema/coercion.py`

Attempt to coerce values to their expected types, detecting lossy conversions.

```python
class TypeCoercer:
    def coerce(self, value: Any, target_type: DataType) -> CoercionResult: ...
    def coerce_batch(self, records: list[dict], schema: Schema) -> list[CoercionBatchResult]: ...

@dataclass
class CoercionResult:
    value: Any               # Coerced value (or original if coercion failed)
    success: bool
    lossy: bool              # True if coercion lost information
    error: str | None = None

@dataclass
class CoercionBatchResult:
    record_index: int
    coerced_values: dict[str, CoercionResult]
    success: bool
```

**Coercion Examples:**

| Original Value | Target Type | Result | Lossy? |
|---------------|-------------|--------|--------|
| "123" | INTEGER | 123 | No |
| "12.5" | INTEGER | 12.5 or 12 | Yes (if truncated) |
| "2024-01-15" | DATETIME | datetime(2024, 1, 15) | No |
| "true" | BOOLEAN | True | No |
| "yes" | BOOLEAN | True | No |
| "1" | BOOLEAN | True | Possibly |

### 2.4 Data Quality Metrics

**File:** `anomalyguard/schema/quality.py`

Tracks data quality metrics over time for trend analysis and alerting.

```python
@dataclass
class QualityMetrics:
    timestamp: datetime
    total_records: int
    valid_records: int
    invalid_records: int
    null_counts: dict[str, int]       # field → null count
    unique_counts: dict[str, int]     # field → unique count
    violation_counts: dict[str, dict[ConstraintType, int]]  # field → constraint → count
    completeness: float               # Overall completeness (1.0 = perfect)
    validity: float                   # Overall validity (1.0 = perfect)
    latency_seconds: float            # Data freshness

class QualityTracker:
    def __init__(self, store: QualityStore):
        self.store = store
    
    def record(self, metrics: QualityMetrics) -> None: ...
    
    def trend(self, field: str, metric: str, window: str = "7d") -> list[QualityMetrics]: ...
    
    def alert_if_degraded(self, metrics: QualityMetrics, thresholds: QualityThresholds) -> list[Alert]: ...
```

---

## File Structure

```
packages/python/schema/
├── __init__.py
├── registry.py               # Schema, Field, DataType, Constraint, SchemaRegistry
├── validator.py              # SchemaValidator, ValidationResult, FieldError
├── coercion.py               # TypeCoercer, CoercionResult
├── quality.py                # QualityMetrics, QualityTracker, QualityThresholds
├── storage.py                # SchemaStorage (SQLite/PostgreSQL)
└── errors.py                 # SchemaValidationError, TypeCoercionError
```
