# Part 5: `anomalyguard-alert` — Notifications & Alerting

## Purpose

When anomalies are detected and remediation is attempted, the system needs to notify relevant people. The alert package provides configurable notification channels, alert rules, and template-based messaging.

## Component Breakdown

### 5.1 Notifier Interface

**File:** `anomalyguard/alert/notifiers.py`

```python
class Notifier(ABC):
    """Base class for notification channels."""
    
    @abstractmethod
    async def send(self, message: AlertMessage) -> bool: ...
    
    @abstractmethod
    async def send_batch(self, messages: list[AlertMessage]) -> list[bool]: ...

@dataclass
class AlertMessage:
    title: str
    body: str
    severity: AlertSeverity
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str | None = None   # Pipeline/source that generated the alert
    metadata: dict | None = None
    attachments: list[Attachment] | None = None

class AlertSeverity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
```

### 5.2 Implementations

**ConsoleNotifier:**
```python
class ConsoleNotifier(Notifier):
    """Print alerts to stdout with optional color coding."""
    
    COLORS = {
        AlertSeverity.DEBUG: "\033[90m",    # Gray
        AlertSeverity.INFO: "\033[94m",     # Blue
        AlertSeverity.WARNING: "\033[93m",  # Yellow
        AlertSeverity.ERROR: "\033[91m",    # Red
        AlertSeverity.CRITICAL: "\033[101m\033[97m",  # White on Red
    }
    
    def send(self, message):
        color = self.COLORS[message.severity]
        reset = "\033[0m"
        print(f"{color}[{message.severity.value.upper()}]{reset} {message.title}")
        if message.body:
            print(f"  {message.body}")
        return True
```

**SlackNotifier:**
```python
class SlackNotifier(Notifier):
    """Send alerts to Slack via webhook."""
    
    def __init__(self, webhook_url: str, channel: str = "#alerts"):
        self.webhook_url = webhook_url
        self.channel = channel
    
    async def send(self, message):
        payload = {
            "channel": self.channel,
            "username": "AnomalyGuard",
            "icon_emoji": ":warning:",
            "attachments": [{
                "color": self._severity_color(message.severity),
                "title": message.title,
                "text": message.body,
                "fields": [
                    {"title": "Severity", "value": message.severity.value, "short": True},
                    {"title": "Source", "value": message.source or "unknown", "short": True},
                ],
                "footer": f"AnomalyGuard • {message.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            }]
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=payload)
        return response.is_success
```

**EmailNotifier:**
```python
class EmailNotifier(Notifier):
    """Send alerts via SMTP email."""
    
    def __init__(self, smtp_config: SMTPConfig, from_addr: str, to_addrs: list[str]):
        self.smtp = smtp_config
        self.from_addr = from_addr
        self.to_addrs = to_addrs
```

**WebhookNotifier:**
```python
class WebhookNotifier(Notifier):
    """Generic HTTP webhook notifier — POST JSON to any endpoint."""
    
    def __init__(self, url: str, headers: dict | None = None, format: str = "json"):
        ...
```

### 5.3 Alert Rules

**File:** `anomalyguard/alert/rules.py`

```python
class AlertRule(ABC):
    """Defines when an alert should be triggered."""
    
    @abstractmethod
    async def evaluate(self, context: AlertContext) -> list[AlertMessage]: ...

class ThresholdRule(AlertRule):
    """Alert when anomaly rate exceeds threshold."""
    
    def __init__(self, threshold: float = 0.05, window: str = "5m"):
        self.threshold = threshold
        self.window = window  # "5m", "1h", "24h"
    
    async def evaluate(self, context):
        rate = context.recent_anomaly_rate(window=self.window)
        if rate > self.threshold:
            return [AlertMessage(
                title=f"Anomaly rate exceeded: {rate:.1%} > {self.threshold:.1%}",
                body=f"...",
                severity=AlertSeverity.WARNING,
            )]
        return []

class TrendRule(AlertRule):
    """Alert when anomaly rate is increasing over time."""
    
    def __init__(self, slope_threshold=0.01, window="1h"):
        ...  # Linear regression on recent rates → alert if positive slope exceeds threshold

class FreshnessRule(AlertRule):
    """Alert when no data received for expected interval."""

class CompoundRule(AlertRule):
    """Combine multiple rules with AND/OR/NOT."""
```

### 5.4 Rate Limiting & Deduplication

**File:** `anomalyguard/alert/rate_limit.py`

```python
class AlertRateLimiter:
    """Prevent alert fatigue by rate-limiting similar alerts."""
    
    def __init__(self, max_per_minute=5, max_per_hour=20):
        self.recent_alerts: deque[AlertMessage] = deque()
    
    def should_send(self, message: AlertMessage) -> bool:
        """Check if this message should be sent (rate limit + dedup)."""
        # Rate limit: check count in rolling window
        # Dedup: if same title in last N messages, skip
        ...
```

---

## File Structure

```
packages/python/alert/
├── __init__.py
├── notifiers.py              # Notifier ABC, AlertMessage, AlertSeverity
├── notifiers/
│   ├── __init__.py
│   ├── console.py            # ConsoleNotifier
│   ├── slack.py              # SlackNotifier
│   ├── email.py              # EmailNotifier
│   └── webhook.py            # WebhookNotifier
├── rules.py                  # AlertRule ABC + implementations
├── rate_limit.py             # AlertRateLimiter
└── templates.py              # Message templates
```
