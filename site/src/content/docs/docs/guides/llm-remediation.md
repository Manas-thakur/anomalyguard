---
title: LLM-assisted remediation
description: Ask a local Ollama model or any OpenAI-compatible endpoint to suggest values for flagged cells.
---

Some flagged values can only be fixed with context: a price that is wrong for its region, a unit that looks like a typo. The optional **LLM suggester** sends each flagged cell, together with its full record, to a language model and attaches the model's suggestion to the review item. It is **off by default**, and it only changes data when you turn on `auto_apply`.

## How it works

For each flagged cell (up to `max_items` per run), AnomalyGuard sends this prompt, filled in with the column, the current value, the reason it was flagged and the whole row as JSON:

```
You are a data cleaning assistant. One value in a record looks wrong.

Column: {column}
Current value: {value}
Problem: {reason}
Full record (JSON): {record}

Suggest the most plausible corrected value for "{column}" using the other fields as context.
Reply with JSON only: {"value": <corrected value>, "confidence": <0..1>, "rationale": "<one sentence>"}
```

For example, `Problem:` would be `[region=east] unit_price=3035 has modified z-score 330.7 vs median 89.08 (threshold 3.5)` and the record `{"order_id": 100787, "timestamp": "2026-01-17 09:00:00", "customer_id": "C0327", "region": "east", "quantity": 5.0, "unit_price": 3035.34, ...}`.

The first JSON object in the reply is parsed into `{value, confidence, rationale}`; confidence is clamped to 0..1. The suggestion and its confidence are stored on the review item and shown in the review inbox, and approving the item without entering a value uses the suggestion.

With `auto_apply: true`, a suggestion whose confidence is at least `min_confidence` is also written into the cleaned data, recorded as a change with strategy `llm`. Its review item is queued with status `applied` (resolved value = the suggestion, note "applied automatically"), so the inbox only shows items that still need a decision.

If the model cannot be reached or the reply has no usable JSON, remediation carries on without a suggestion; the reason (for example `LLM unavailable: ...`) is stored as the item's rationale.

:::caution[Privacy]
The full record of every flagged row is sent to the model. Use a local model (Ollama, or an OpenAI-compatible server on your own machine) for data that must not leave it.
:::

## Ollama

Runs locally; nothing leaves the machine. Install [Ollama](https://ollama.com), pull a model, and enable the suggester in the pipeline:

```bash
ollama pull llama3.1:8b
```

```yaml
remediation:
  default: {outlier: cap}
  columns:
    unit_price: {outlier: flag}
  llm:
    enabled: true
    provider: ollama
    model: llama3.1:8b
    # base_url: http://localhost:11434
    auto_apply: false
```

AnomalyGuard calls `POST {base_url}/api/generate` with `"format": "json"` and `"stream": false`.

## OpenAI-compatible endpoints

`provider: openai` works with any server that implements `POST {base_url}/chat/completions`: hosted APIs, or local servers such as vLLM, LM Studio and the llama.cpp server.

```yaml
remediation:
  llm:
    enabled: true
    provider: openai
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1      # or http://localhost:8000/v1 for a local server
    api_key_env: OPENAI_API_KEY              # sent as Authorization: Bearer <key>
    auto_apply: true
    min_confidence: 0.9
    max_items: 50
```

The key is read from the environment variable named by `api_key_env` (default `OPENAI_API_KEY`) and is never written to the YAML.

## Options

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Turn the suggester on |
| `provider` | `ollama` | `ollama` or `openai` |
| `model` | `llama3.1:8b` | Model name |
| `base_url` | `http://localhost:11434` (ollama), `https://api.openai.com/v1` (openai) | Server URL |
| `api_key_env` | `OPENAI_API_KEY` | Variable holding the key (used for `openai` only) |
| `timeout` | `60` | Seconds per request |
| `temperature` | `0.0` | Sampling temperature |
| `auto_apply` | `false` | Write confident suggestions into the data |
| `min_confidence` | `0.8` | Threshold for `auto_apply` |
| `max_items` | `20` | Flagged cells sent per run |

Only cells are sent; flagged whole rows (from multivariate detectors) are skipped. The suggester is available in pipelines and in Python; the CLI `fix` command and web app analyses do not use it.

## In Python

```python
from anomalyguard.remediate import LLMSuggester, RemediationPipeline

llm = LLMSuggester(provider="ollama", model="llama3.1:8b")
result = RemediationPipeline(
    {"columns": {"unit_price": {"outlier": "flag"}}},
    llm=llm, llm_auto_apply=False, llm_min_confidence=0.8, llm_max_items=20,
).run(df, report)

for item in result.flagged:
    print(item.column, item.value, item.suggestion, item.suggestion_confidence, item.suggestion_rationale)
```
