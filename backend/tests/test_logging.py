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


def test_redact_bare_query_key():
    """Sorgu dizgesindeki çıplak key= parametresi de maskelenir
    (httpx URL'lerinde YouTube anahtarı bu şekildedi)."""
    from app.logging_config import _redact

    out = _redact("GET https://api?part=1&key=AIzaSyXYZ123")
    assert "AIzaSyXYZ123" not in out
    assert "key=[REDACTED]" in out


def test_httpx_logger_demoted_to_warning():
    """httpx INFO'da tam URL bastığı için susturulur."""
    import logging

    from app.logging_config import setup_logging

    setup_logging("info")
    assert logging.getLogger("httpx").level == logging.WARNING
