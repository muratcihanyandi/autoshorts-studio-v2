"""Ayni icerigin farkli mirror kanallardan tekrar islenmesini onler.

Canli bulgu (2026-10-21, Gorev 8): izlenen iki kaynak kanal (Craftest
ve 2kan) ayni RRaenee tepki videolarini yukluyor — ayni icerik,
farkli YouTube video kimligi ve biraz farkli baslik bicimi
("X | Tepki | @user" vs "X Tepki! @user"). Kimlik bazli dedupe
(source_videos unique (kanal, video)) bunu gormez; baslik
normalizasyonu + benzerlik esigi ile yakalanir.

Kural (konservatif): normalize edilmis basliklar birebir eslesir
VEYA token kapsamasi %90+ (kisa basligin kelimeleri uzun basligin
icinde; her iki tarafta en az 3 token) VE basliktaki sayi tokenlari
ayni — "Motosiklet Kazalarina Tepki! #12" ile "#13" gibi gercekten
farkli bolumler duplicate sayilmaz.
"""
from __future__ import annotations

import re
from typing import Iterable

# Turkce karakterler ASCII'ye katlanir; casefold 'I'->'i' davranisiyla
# birlikte buyuk/kucuk bicim farklari etkisiz kalir.
_TR_MAP = str.maketrans("çğıöşü", "cgiosu")

_HANDLE_RE = re.compile(r"@\w+")
_JUNK_RE = re.compile(r"[^a-z0-9]+")

# Kapsama esigi: ayni icerik farkli bicimde yazildiginda kisa baslik
# uzun basligin icinde kaybolur; esik yanlis pozitiflere karsi yuksek.
COVERAGE_THRESHOLD = 0.9
MIN_TOKENS_FOR_COVERAGE = 3


def normalize_title(title: str) -> str:
    """Basligi karsilastirmaya hazir hale getir: kucuk harf, Turkce
    karakter katlamasi, kullanici adi (@handle) ayiklama, noktalama
    ve gorunmez karakterler bosluga, bosluklar sikistirilir."""
    text = (title or "").casefold()
    text = text.translate(_TR_MAP)
    text = _HANDLE_RE.sub(" ", text)
    text = _JUNK_RE.sub(" ", text)
    return " ".join(text.split())


def _number_tokens(tokens: set[str]) -> set[str]:
    """Seri/bolum/ayrt edici sayilar: '12', '11i', '2026' gibi."""
    return {t for t in tokens if any(ch.isdigit() for ch in t)}


def titles_match(norm_a: str, norm_b: str) -> bool:
    """Normalize edilmis iki baslik ayni icerik mi?"""
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    a = set(norm_a.split())
    b = set(norm_b.split())
    if not a or not b:
        return False
    # Sayilar farkliysa kesinlikle farkli icerik (seri bolumleri).
    if _number_tokens(a) != _number_tokens(b):
        return False
    if min(len(a), len(b)) < MIN_TOKENS_FOR_COVERAGE:
        return False
    coverage = len(a & b) / min(len(a), len(b))
    return coverage >= COVERAGE_THRESHOLD


def find_duplicate_title(
    normalized: str,
    existing: Iterable[tuple[str, int]],
) -> int | None:
    """Normalize edilmis basligi mevcut (norm, video_id) ciftleriyle
    karsilastir; eslesen ilk mevcut videonun kimligini doner."""
    for norm, video_id in existing:
        if titles_match(normalized, norm):
            return video_id
    return None
