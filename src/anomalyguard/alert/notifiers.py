"""Console, JSONL file, generic webhook, Slack and email notifiers."""

from __future__ import annotations

import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any, TextIO

import httpx

from anomalyguard.alert.base import AlertMessage, Notifier, Severity

COLORS = {
    Severity.DEBUG: "\033[90m",
    Severity.INFO: "\033[94m",
    Severity.WARNING: "\033[93m",
    Severity.ERROR: "\033[91m",
    Severity.CRITICAL: "\033[97;41m",
}
RESET = "\033[0m"


class ConsoleNotifier(Notifier):
    """Print alerts; colours are used only when the stream is a terminal."""

    kind = "console"

    def __init__(
        self,
        min_severity: Severity | str = Severity.INFO,
        stream: TextIO | None = None,
        color: bool | None = None,
    ):
        super().__init__(min_severity)
        self.stream = stream
        self.color = color

    def send(self, message: AlertMessage) -> bool:
        stream = self.stream or sys.stdout
        use_color = (
            self.color
            if self.color is not None
            else (hasattr(stream, "isatty") and stream.isatty())
        )
        tag = f"[{message.severity.value.upper()}]"
        if use_color:
            tag = f"{COLORS[message.severity]}{tag}{RESET}"
        src = f" ({message.source})" if message.source else ""
        print(f"{tag} {message.title}{src}", file=stream)
        if message.body:
            for line in message.body.splitlines():
                print(f"    {line}", file=stream)
        return True


class FileNotifier(Notifier):
    """Append alerts as JSON lines to ``path``."""

    kind = "file"

    def __init__(self, path: str | Path, min_severity: Severity | str = Severity.INFO):
        super().__init__(min_severity)
        self.path = Path(path)

    def send(self, message: AlertMessage) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(message.to_dict(), default=str) + "\n")
        return True


class WebhookNotifier(Notifier):
    """POST the alert as JSON to any URL. ``format="slack"`` sends a Slack
    incoming-webhook payload instead of the raw message."""

    kind = "webhook"

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        format: str = "json",
        min_severity: Severity | str = Severity.WARNING,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        super().__init__(min_severity)
        if not url:
            raise ValueError("Webhook notifier needs a url")
        self.url = url
        self.headers = headers or {}
        self.format = format
        self.timeout = timeout
        self.transport = transport

    def payload(self, message: AlertMessage) -> dict[str, Any]:
        if self.format == "slack":
            return slack_payload(message)
        return message.to_dict()

    def send(self, message: AlertMessage) -> bool:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(self.url, json=self.payload(message), headers=self.headers)
            return resp.is_success
        except httpx.HTTPError:
            return False


SLACK_COLORS = {
    Severity.DEBUG: "#9e9e9e",
    Severity.INFO: "#2196f3",
    Severity.WARNING: "#ff9800",
    Severity.ERROR: "#f44336",
    Severity.CRITICAL: "#b71c1c",
}


def slack_payload(message: AlertMessage) -> dict[str, Any]:
    fields = [
        {"title": "Severity", "value": message.severity.value, "short": True},
        {"title": "Source", "value": message.source or "-", "short": True},
    ]
    return {
        "text": f"[{message.severity.value.upper()}] {message.title}",
        "attachments": [
            {
                "color": SLACK_COLORS[message.severity],
                "title": message.title,
                "text": message.body,
                "fields": fields,
                "footer": f"AnomalyGuard | {message.timestamp}",
            }
        ],
    }


class SlackNotifier(WebhookNotifier):
    """Slack incoming webhook (``https://hooks.slack.com/services/...``)."""

    kind = "slack"

    def __init__(self, url: str, min_severity: Severity | str = Severity.WARNING, **kw: Any):
        super().__init__(url, format="slack", min_severity=min_severity, **kw)


class EmailNotifier(Notifier):
    """Send alerts over SMTP. The password is read from ``password_env``."""

    kind = "email"

    def __init__(
        self,
        host: str,
        to_addrs: list[str] | str,
        from_addr: str = "anomalyguard@localhost",
        port: int = 587,
        username: str | None = None,
        password_env: str | None = "ANOMALYGUARD_SMTP_PASSWORD",
        use_tls: bool = True,
        min_severity: Severity | str = Severity.ERROR,
        timeout: float = 15.0,
    ):
        super().__init__(min_severity)
        self.host, self.port = host, port
        self.to_addrs = [to_addrs] if isinstance(to_addrs, str) else list(to_addrs)
        self.from_addr = from_addr
        self.username = username
        self.password_env = password_env
        self.use_tls = use_tls
        self.timeout = timeout

    def build(self, message: AlertMessage) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"[AnomalyGuard][{message.severity.value.upper()}] {message.title}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        lines = [
            message.title,
            "",
            message.body,
            "",
            f"Source: {message.source or '-'}",
            f"Time: {message.timestamp}",
        ]
        if message.metadata:
            lines += ["", json.dumps(message.metadata, indent=2, default=str)]
        msg.set_content("\n".join(lines))
        return msg

    def send(self, message: AlertMessage) -> bool:
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                password = os.environ.get(self.password_env) if self.password_env else None
                if self.username and password:
                    smtp.login(self.username, password)
                smtp.send_message(self.build(message))
            return True
        except (OSError, smtplib.SMTPException):
            return False


NOTIFIER_TYPES = {
    "console": ConsoleNotifier,
    "file": FileNotifier,
    "jsonl": FileNotifier,
    "webhook": WebhookNotifier,
    "slack": SlackNotifier,
    "email": EmailNotifier,
}


def create_notifier(config: dict[str, Any], base_dir: str | Path | None = None) -> Notifier:
    cfg = dict(config)
    kind = str(cfg.pop("type", "console")).lower()
    if kind not in NOTIFIER_TYPES:
        raise ValueError(f"Unknown notifier '{kind}'. Known: {sorted(NOTIFIER_TYPES)}")
    if "severity" in cfg and "min_severity" not in cfg:
        cfg["min_severity"] = cfg.pop("severity")
    if (
        kind in ("file", "jsonl")
        and base_dir is not None
        and not Path(cfg.get("path", "")).is_absolute()
    ):
        cfg["path"] = str(Path(base_dir) / cfg["path"])
    if "url_env" in cfg:
        cfg["url"] = os.environ.get(cfg.pop("url_env"), "")
    try:
        return NOTIFIER_TYPES[kind](**cfg)
    except TypeError as exc:
        raise ValueError(f"Invalid options for notifier '{kind}': {exc}") from exc
