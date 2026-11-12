from __future__ import annotations

import io
import json

import httpx
import pytest

from anomalyguard.alert import (
    AlertManager,
    AlertMessage,
    AlertRule,
    ConsoleNotifier,
    EmailNotifier,
    FileNotifier,
    RateLimiter,
    Severity,
    SlackNotifier,
    WebhookNotifier,
    create_notifier,
)


def msg(sev: Severity = Severity.WARNING, title: str = "anomaly_rate high") -> AlertMessage:
    return AlertMessage(title, "body text", sev, source="orders", rule=title)


def test_severity_ordering():
    assert Severity.CRITICAL > Severity.ERROR >= Severity.ERROR > Severity.WARNING
    assert Severity.DEBUG < Severity.INFO <= Severity.INFO


def test_console_notifier_respects_min_severity():
    buf = io.StringIO()
    n = ConsoleNotifier("warning", stream=buf)
    assert n.accepts(msg(Severity.ERROR)) and not n.accepts(msg(Severity.INFO))
    n.send(msg())
    out = buf.getvalue()
    assert "[WARNING] anomaly_rate high (orders)" in out and "\033[" not in out
    buf2 = io.StringIO()
    ConsoleNotifier(stream=buf2, color=True).send(msg(Severity.ERROR))
    assert "\033[91m" in buf2.getvalue()


def test_file_notifier(tmp_path):
    n = FileNotifier(tmp_path / "a" / "alerts.jsonl")
    n.send_batch([msg(), msg(Severity.ERROR)])
    lines = (tmp_path / "a" / "alerts.jsonl").read_text().splitlines()
    assert [json.loads(x)["severity"] for x in lines] == ["warning", "error"]


def test_webhook_and_slack_payloads():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("x-token"), json.loads(request.content)))
        return httpx.Response(200)

    t = httpx.MockTransport(handler)
    assert WebhookNotifier(
        "https://hooks.example.test/x", headers={"x-token": "t"}, transport=t
    ).send(msg())
    assert SlackNotifier("https://hooks.slack.test/services/x", transport=t).send(
        msg(Severity.CRITICAL)
    )
    assert seen[0][0] == "t" and seen[0][1]["title"] == "anomaly_rate high"
    slack = seen[1][1]
    assert slack["text"].startswith("[CRITICAL]") and slack["attachments"][0]["color"] == "#b71c1c"

    failing = WebhookNotifier(
        "https://hooks.example.test/x", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert failing.send(msg()) is False

    def boom(request):
        raise httpx.ConnectError("refused")

    assert (
        WebhookNotifier("https://x.test", transport=httpx.MockTransport(boom)).send(msg()) is False
    )
    with pytest.raises(ValueError):
        WebhookNotifier("")


def test_email_notifier(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, m):
            sent["msg"] = m

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setenv("AG_SMTP_PW", "pw")
    n = EmailNotifier(
        "smtp.example.test", ["ops@example.test"], username="bot", password_env="AG_SMTP_PW"
    )
    assert n.send(msg(Severity.CRITICAL))
    assert (
        sent["host"] == ("smtp.example.test", 587)
        and sent["tls"]
        and sent["login"] == ("bot", "pw")
    )
    assert "[CRITICAL]" in sent["msg"]["Subject"] and sent["msg"]["To"] == "ops@example.test"


def test_rules():
    r = AlertRule("anomaly_rate", ">", 0.05, "warning")
    assert r.evaluate({"anomaly_rate": 0.01}) is None
    m = r.evaluate({"anomaly_rate": 0.1, "rows": 100}, source="p")
    assert m.severity == Severity.WARNING and "anomaly_rate" in m.title and "rows=100" in m.body
    assert AlertRule("x", "<", 1).evaluate({}) is None
    ch = AlertRule.from_dict(
        {
            "metric": "anomaly_rate",
            "type": "change",
            "op": ">",
            "threshold": 0.02,
            "severity": "error",
        }
    )
    assert ch.evaluate({"anomaly_rate": 0.1}) is None  # no previous run
    assert (
        ch.evaluate({"anomaly_rate": 0.1, "previous": {"anomaly_rate": 0.01}}).severity
        == Severity.ERROR
    )
    custom = AlertRule("quality_score", "<", 0.9, message="Quality dropped to {quality_score:.0%}")
    assert custom.evaluate({"quality_score": 0.5}).title == "Quality dropped to 50%"
    with pytest.raises(ValueError):
        AlertRule("x", "=~", 1)


def test_rate_limiter_dedup_window_and_persistence(tmp_path):
    now = [1000.0]
    rl = RateLimiter(
        max_per_window=2,
        window_seconds=60,
        dedup_seconds=30,
        state_path=tmp_path / "rl.json",
        clock=lambda: now[0],
    )
    assert rl.allow(msg(title="a")) == (True, "ok")
    assert rl.allow(msg(title="a")) == (False, "duplicate")
    assert rl.allow(msg(title="b"))[0]
    assert rl.allow(msg(title="c")) == (False, "rate_limited")
    # state survives a new process
    rl2 = RateLimiter(
        max_per_window=2,
        window_seconds=60,
        dedup_seconds=30,
        state_path=tmp_path / "rl.json",
        clock=lambda: now[0],
    )
    assert rl2.allow(msg(title="a")) == (False, "duplicate")
    now[0] += 61
    assert rl2.allow(msg(title="a")) == (True, "ok")


def test_manager_routes_by_severity(tmp_path):
    buf = io.StringIO()
    console = ConsoleNotifier("error", stream=buf)
    file = FileNotifier(tmp_path / "all.jsonl", min_severity="info")
    mgr = AlertManager(
        [console, file],
        [
            AlertRule("anomaly_rate", ">", 0.05, "warning"),
            AlertRule("quality_score", "<", 0.9, "error"),
        ],
    )
    records = mgr.process({"anomaly_rate": 0.2, "quality_score": 0.5}, source="p")
    assert [r.status for r in records] == ["sent", "sent"]
    assert records[0].channels == ["file"] and set(records[1].channels) == {"console", "file"}
    assert "[ERROR] quality_score" in buf.getvalue() and "[WARNING]" not in buf.getvalue()
    mgr2 = AlertManager(
        [ConsoleNotifier("critical", stream=io.StringIO())], [AlertRule("x", ">", 0)]
    )
    assert mgr2.process({"x": 1})[0].status == "filtered"


def test_create_notifier(tmp_path, monkeypatch):
    n = create_notifier(
        {"type": "file", "path": "alerts.jsonl", "severity": "error"}, base_dir=tmp_path
    )
    assert (
        isinstance(n, FileNotifier)
        and n.min_severity == Severity.ERROR
        and n.path.parent == tmp_path
    )
    monkeypatch.setenv("HOOK", "https://hooks.slack.test/abc")
    s = create_notifier({"type": "slack", "url_env": "HOOK"})
    assert isinstance(s, SlackNotifier) and s.url.endswith("abc")
    with pytest.raises(ValueError):
        create_notifier({"type": "pager"})
    with pytest.raises(ValueError):
        create_notifier({"type": "console", "nope": 1})
