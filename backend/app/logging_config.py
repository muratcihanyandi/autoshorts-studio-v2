"""Structured JSON logging with basic secret redaction.

One JSON object per line on stdout. Uvicorn's own access log is demoted to
WARNING to keep the output stream structured.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_REDACT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|api_key|apikey|key|token|authorization)\b(\s*[=:]\s*)\S+"
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _redact(message: str) -> str:
    return _REDACT_PATTERN.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", message)


def setup_logging(level: str = "info") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    try:
        root.setLevel(level.upper())
    except ValueError:
        root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # httpx INFO satirlari istegin TAM URL'ini basar; sorgu dizgesindeki
    # YouTube anahtari boylece konteyner loglarina dustu (canli bulgu
    # 2026-10-20). Kendi isteklerimiz zaten yapisal loglaniyor.
    logging.getLogger("httpx").setLevel(logging.WARNING)
