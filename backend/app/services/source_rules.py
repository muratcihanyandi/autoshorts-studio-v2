"""Source filter rules (JSONB on source_channels).

Supported rule keys:
- exclude_title_patterns: list of case-insensitive substrings; a match
  excludes the video.
- max_age_days: videos older than this are excluded.

The evaluator returns a human-readable Turkish reason for exclusions so
decisions stay explainable; ``None`` means eligible.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta


def evaluate_source_rules(
    rules: dict | None,
    *,
    title: str,
    published_at: datetime | None,
) -> str | None:
    """Return an exclusion reason, or None when the video is eligible."""
    if not isinstance(rules, dict) or not rules:
        return None

    for pattern in rules.get("exclude_title_patterns") or []:
        if isinstance(pattern, str) and pattern and pattern.lower() in title.lower():
            return f"başlık kuralı: {pattern}"

    max_age_days = rules.get("max_age_days")
    if max_age_days is not None and published_at is not None:
        cutoff = datetime.now(UTC) - timedelta(days=int(max_age_days))
        if published_at.tzinfo is None:
            # sqlite tarihleri naive döner; karşılaştırma aynı tarafta kalsın.
            cutoff = cutoff.replace(tzinfo=None)
        if published_at < cutoff:
            return f"yaş kuralı: {max_age_days} günden eski"

    return None
