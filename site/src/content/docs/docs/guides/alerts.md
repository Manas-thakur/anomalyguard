---
title: Alerts and notifiers
description: Set up console, file, webhook, Slack and email notifiers, with secrets from environment variables.
---

Alerts are configured in the `alerts` section of a [pipeline](/anomalyguard/docs/reference/pipeline-yaml/#alerts). This guide covers the notifiers; [Alerts](/anomalyguard/docs/concepts/alerts/) explains rules, metrics and rate limits.

```yaml
alerts:
  rules:
    - {metric: anomaly_rate, op: ">", value: 0.03, severity: warning}
    - {metric: quality_score, op: "<", value: 0.95, severity: error}
  notifiers:
    - {type: console, min_severity: info}
    - {type: file, path: out/alerts.jsonl}
    - {type: slack, url: "${SLACK_WEBHOOK_URL}", min_severity: error}
  rate_limit: {dedup_seconds: 3600, window_seconds: 3600, max_per_window: 20}
```

Every notifier takes `type` and `min_severity` (alias `severity`). Default `min_severity` depends on the type, as listed below.

If a pipeline has no `notifiers` key, `anomalyguard run` prints alerts to the console. Pipelines run from the web app have no console, so add a notifier if you want alerts from those runs delivered somewhere. `alerts.enabled: false` turns alerting off for a pipeline.

## console

Prints `[SEVERITY] title (source)` and the metrics. Colours are used only when the output is a terminal.

| Key | Default |
|---|---|
| `min_severity` | `info` |

## file

Appends each alert as one JSON line. Type `jsonl` is an alias. A relative `path` is resolved against the pipeline file's folder.

| Key | Default |
|---|---|
| `path` | required |
| `min_severity` | `info` |

Each line has `title`, `body`, `severity`, `source`, `rule`, `metadata` (`metric`, `observed`, `threshold`) and `timestamp`.

## webhook

POSTs the alert as JSON (the same fields as the file notifier) to any URL. Delivery fails if the response is not 2xx.

| Key | Default |
|---|---|
| `url` (or `url_env`: the name of an environment variable holding it) | required |
| `headers` | none |
| `format` | `json` (`slack` sends a Slack payload) |
| `timeout` | `10` seconds |
| `min_severity` | `warning` |

```yaml
- type: webhook
  url: https://example.com/hooks/anomalyguard
  headers: {X-Token: "${HOOK_TOKEN}"}
```

## slack

A webhook with a Slack incoming-webhook payload: a colour-coded attachment with the title, metrics, severity and source.

| Key | Default |
|---|---|
| `url` (or `url_env`) | required, `https://hooks.slack.com/services/...` |
| `timeout` | `10` seconds |
| `min_severity` | `warning` |

```yaml
- {type: slack, url_env: SLACK_WEBHOOK_URL, min_severity: error}
```

## email

Sends one message per alert over SMTP, with the subject `[AnomalyGuard][SEVERITY] title`.

| Key | Default |
|---|---|
| `host` | required |
| `to_addrs` | required (a list, or one address) |
| `from_addr` | `anomalyguard@localhost` |
| `port` | `587` |
| `username` | none (no login) |
| `password_env` | `ANOMALYGUARD_SMTP_PASSWORD` |
| `use_tls` | `true` (STARTTLS) |
| `timeout` | `15` seconds |
| `min_severity` | `error` |

```yaml
- type: email
  host: smtp.example.com
  to_addrs: [ops@example.com]
  username: alerts-bot
  password_env: ANOMALYGUARD_SMTP_PASSWORD
  min_severity: critical
```

The password is read from the environment at send time and never stored in the YAML.

## Secrets

Keep secrets out of pipeline files:

- `${VAR}` and `${VAR:-default}` anywhere in the YAML are replaced with environment variables when the file is loaded.
- `url_env` (webhook, Slack) and `password_env` (email) name the variable to read.

:::caution
A webhook or Slack notifier with an empty URL is a configuration error, and the whole run fails. If `${SLACK_WEBHOOK_URL}` is not set, the URL is empty. Comment the notifier out (as the examples do) or use `${SLACK_WEBHOOK_URL:-...}` until the variable is set. `anomalyguard doctor` reports notifiers whose secrets are missing.
:::

## Checking the setup

```bash
anomalyguard doctor
```

The **Notifiers** section lists every notifier of every pipeline it finds, with its minimum severity and whether its URL or password is available. The web app's **Settings** page shows the same information.

## In Python

```python
from anomalyguard.alert import AlertManager, AlertRule, ConsoleNotifier, RateLimiter, SlackNotifier

manager = AlertManager(
    notifiers=[ConsoleNotifier("info"), SlackNotifier("https://hooks.slack.com/services/...", min_severity="error")],
    rules=[AlertRule("anomaly_rate", ">", 0.03, "warning")],
    rate_limiter=RateLimiter(max_per_window=20, dedup_seconds=3600),
)
records = manager.process({"anomaly_rate": 0.047, "rows": 1000}, source="orders")
print([r.status for r in records])   # ['sent']
```

`create_notifier(dict)` builds a notifier from the same mapping as the YAML.
