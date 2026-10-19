"""Source filter rules (JSONB on source_channels).

Supported rule keys:
- exclude_title_patterns: list of case-insensitive substrings; a match
  excludes the video.
- max_age_days: videos older than this are excluded.
- require_reaction_content: when true, only reaction/tepkime videos are
  eligible. The check is a POSITIVE title match (see REACTION_TITLE_
  MARKERS): a title that names a reaction ("Reacting to funny moments")
  stays eligible even though it also mentions funny moments — the
  publisher is reacting, which is allowed; their own edits (funny
  moments compilations without a reaction cue) are excluded.

The evaluator returns a human-readable Turkish reason for exclusions so
decisions stay explainable; ``None`` means eligible.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Baslikta tepki/tepkime gostergesi aranan alt diziler. "react" tek bina
# react/reacts/reacting/reaction kelimelerini kapsar; "watching" izleme
# tepkilerini (ör. "RRaenee watching funny moments") yakalar.
REACTION_TITLE_MARKERS = (
    "react",
    "watching",
    "izliyorum",
    "izlerken",
    "tepki",
    "reaksiyon",
)

# require_reaction_content kuralindan kaynaklanan hariç gerekçelerinin
# öneki; geri alma (kural kapatilinca) yalnız bu önekle işaretlenen
# kayıtlara dokunur — manuel hariçler asla geri gelmez.
REACTION_RULE_PREFIX = "tepkime kuralı"

# max_age_days kuralının hariç gerekçe öneki; pencere genişletilince
# yalnız bu önekle hariç tutulanlar yeniden değerlendirilir.
AGE_RULE_PREFIX = "yaş kuralı"


def is_reaction_title(title: str) -> bool:
    """True when the title carries a reaction cue."""
    lowered = title.lower()
    return any(marker in lowered for marker in REACTION_TITLE_MARKERS)


def age_exclusion(
    rules: dict | None, *, published_at: datetime | None
) -> str | None:
    """Return the age-rule exclusion reason alone, or None.

    Zamanla değişen tek kural budur: keşifte uygun olan bir video kuyrukta
    beklerken pencere dışına çıkabilir — besleme sorguları yalnız bu
    denetimi tekrarlar, başlık kuralları yeniden uygulanmaz.
    """
    if not isinstance(rules, dict):
        return None
    max_age_days = rules.get("max_age_days")
    if max_age_days is None or published_at is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(days=int(max_age_days))
    if published_at.tzinfo is None:
        # sqlite tarihleri naive döner; karşılaştırma aynı tarafta kalsın.
        cutoff = cutoff.replace(tzinfo=None)
    if published_at < cutoff:
        return f"{AGE_RULE_PREFIX}: {max_age_days} günden eski"
    return None


def evaluate_source_rules(
    rules: dict | None,
    *,
    title: str,
    published_at: datetime | None,
) -> str | None:
    """Return an exclusion reason, or None when the video is eligible."""
    if not isinstance(rules, dict) or not rules:
        return None

    if rules.get("require_reaction_content") and not is_reaction_title(title):
        return f"{REACTION_RULE_PREFIX}: başlıkta tepki göstergesi yok"

    for pattern in rules.get("exclude_title_patterns") or []:
        if isinstance(pattern, str) and pattern and pattern.lower() in title.lower():
            return f"başlık kuralı: {pattern}"

    return age_exclusion(rules, published_at=published_at)
