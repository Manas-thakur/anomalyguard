"""REST API source with page-number, offset, cursor and next-link pagination."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pandas as pd

from anomalyguard.ingest.base import IngestError, Source
from anomalyguard.ingest.files import extract_path


class RESTSource(Source):
    """Fetch JSON records from an HTTP endpoint.

    ``pagination`` examples::

        {"type": "page", "param": "page", "start": 1, "size_param": "per_page"}
        {"type": "offset", "param": "offset", "limit_param": "limit"}
        {"type": "cursor", "param": "cursor", "cursor_path": "meta.next_cursor"}
        {"type": "next_link", "next_path": "links.next"}

    ``api_key_env`` reads a token from the environment and sends it in
    ``api_key_header`` (default ``Authorization: Bearer <token>``).
    """

    kind = "rest"

    def __init__(
        self,
        url: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        records_path: str | None = None,
        pagination: dict[str, Any] | None = None,
        max_pages: int = 100,
        timeout: float = 30.0,
        api_key_env: str | None = None,
        api_key_header: str = "Authorization",
        rate_limit_seconds: float = 0.0,
        name: str | None = None,
        cursor: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        super().__init__(name or "rest", cursor)
        self.url = url
        self.method = method.upper()
        self.params = dict(params or {})
        self.headers = dict(headers or {})
        self.records_path = records_path
        self.pagination = pagination or {}
        self.max_pages = max_pages
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds
        self.transport = transport
        if api_key_env:
            token = os.environ.get(api_key_env)
            if token:
                self.headers[api_key_header] = (
                    f"Bearer {token}" if api_key_header.lower() == "authorization" else token
                )

    def _records(self, payload: Any) -> list[Any]:
        records = extract_path(payload, self.records_path)
        if isinstance(records, dict):
            return [records]
        if not isinstance(records, list):
            raise IngestError(f"Expected a list of records at '{self.records_path or '$'}'")
        return records

    def _iter_batches(self, batch_size: int) -> Iterator[pd.DataFrame]:
        ptype = self.pagination.get("type")
        params = dict(self.params)
        url: str | None = self.url
        if ptype == "page":
            params[self.pagination.get("param", "page")] = self.pagination.get("start", 1)
            if "size_param" in self.pagination:
                params[self.pagination["size_param"]] = self.pagination.get("size", batch_size)
        elif ptype == "offset":
            params[self.pagination.get("param", "offset")] = 0
            params[self.pagination.get("limit_param", "limit")] = self.pagination.get(
                "size", batch_size
            )

        with httpx.Client(
            timeout=self.timeout, transport=self.transport, headers=self.headers
        ) as client:
            for page in range(self.max_pages):
                if url is None:
                    break
                if page and self.rate_limit_seconds:
                    time.sleep(self.rate_limit_seconds)
                try:
                    resp = client.request(self.method, url, params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise IngestError(f"REST request failed: {exc}") from exc
                payload = resp.json()
                records = self._records(payload)
                if records:
                    yield pd.json_normalize(records)
                if not ptype or not records:
                    break
                if ptype == "page":
                    key = self.pagination.get("param", "page")
                    params[key] = int(params[key]) + 1
                elif ptype == "offset":
                    key = self.pagination.get("param", "offset")
                    params[key] = int(params[key]) + len(records)
                elif ptype == "cursor":
                    try:
                        nxt = extract_path(
                            payload, self.pagination.get("cursor_path", "next_cursor")
                        )
                    except IngestError:
                        nxt = None
                    if not nxt:
                        break
                    params[self.pagination.get("param", "cursor")] = nxt
                elif ptype == "next_link":
                    try:
                        url = extract_path(payload, self.pagination.get("next_path", "next"))
                    except IngestError:
                        url = None
                    params = {}
                else:
                    raise IngestError(f"Unknown pagination type: {ptype}")

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "url": self.url}
