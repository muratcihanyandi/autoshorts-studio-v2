"""Structured logging tests."""
from __future__ import annotations

import json
import logging

from app.logging_config import JsonFormatter, _redact


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=None, exc_info=None,
    )


def test_json_formatter_emits_valid_json() -> None:
    line = JsonFormatter().format(_make_record("pipeline started"))
    payload = json.loads(line)
    assert payload["message"] == "pipeline started"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert "ts" in payload


def test_redact_hides_secret_assignments() -> None:
    message = "connect failed password=hunter2secret token=abc123def api_key=k_1234567890"  # secret-scan-ok
    redacted = _redact(message)
    assert "hunter2secret" not in redacted
    assert "abc123def" not in redacted
    assert "k_1234567890" not in redacted
    assert redacted.count("[REDACTED]") == 3
