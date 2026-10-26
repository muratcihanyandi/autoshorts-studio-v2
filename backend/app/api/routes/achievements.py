"""YouTube kanal basarimlari ve PlayStation trophy API'si.

Kanalin YouTube istatistikleri ve yuklenen videolari uzerinden PlayStation
tarzi kupa derecelerini (Bronz, Gumus, Altin, Platin) ve para kazanma (YPP)
ilerlemesini hesaplar.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.routes.settings import effective_settings
from app.services.auth_service import ensure_channel_access
from app.services.youtube_client import YouTubeQuotaExceeded
from app.services.youtube_manage import YouTubeManageError, YouTubeManageService

router = APIRouter(tags=["achievements"])


def _compute_achievements_payload(data: dict[str, Any]) -> dict[str, Any]:
    """YouTube video listesi ve istatistiklerinden basarim metriklerini cikarir."""
    videos = data.get("videos") or []
    yt_stats = data.get("youtube") or {}

    total_views = yt_stats.get("view_count") or sum(
        v.get("view_count", 0) for v in videos
    )
    subscriber_count = yt_stats.get("subscriber_count") or 0
    total_videos = yt_stats.get("video_count") or len(videos)

    total_likes = sum(v.get("like_count", 0) for v in videos)
    total_comments = sum(v.get("comment_count", 0) for v in videos)

    shorts = [v for v in videos if v.get("orientation") == "vertical"]
    horizontals = [v for v in videos if v.get("orientation") == "horizontal"]

    shorts_count = len(shorts)
    shorts_views = sum(v.get("view_count", 0) for v in shorts)
    horizontal_count = len(horizontals)
    horizontal_views = sum(v.get("view_count", 0) for v in horizontals)

    # 1 gunde alinan en yuksek izlenme
    daily_buckets: dict[str, int] = {}
    max_single_views = 0
    for v in videos:
        vc = v.get("view_count", 0)
        if vc > max_single_views:
            max_single_views = vc
        pub = v.get("published_at")
        if pub and isinstance(pub, str) and len(pub) >= 10:
            day = pub[:10]
            daily_buckets[day] = daily_buckets.get(day, 0) + vc

    max_bucket_views = max(daily_buckets.values()) if daily_buckets else 0
    max_daily_views = max(max_single_views, max_bucket_views)

    # Yaklasik izlenme saati (yatay video * 4.5 dk / 60)
    watch_hours = round((horizontal_views * 4.5) / 60)

    # Etkilesim orani: (likes + comments) / total_views * 100
    engagement_rate = (
        round(((total_likes + total_comments) / total_views) * 100, 2)
        if total_views > 0
        else 0.0
    )

    # 16 Adet Kupa Tanimi
    definitions = [
        # Bronz Kupalar
        {
            "id": "first_stage",
            "title": "İlk Sahne",
            "tier": "bronze",
            "category": "first_steps",
            "target": 1,
            "unit": "video",
            "current": total_videos,
            "unlocked": total_videos >= 1,
        },
        {
            "id": "audience_gathering",
            "title": "Seyirci Toplanıyor",
            "tier": "bronze",
            "category": "views",
            "target": 1000,
            "unit": "izlenme",
            "current": total_views,
            "unlocked": total_views >= 1000,
        },
        {
            "id": "loyal_followers",
            "title": "Sadık Takipçiler",
            "tier": "bronze",
            "category": "community",
            "target": 50,
            "unit": "abone",
            "current": subscriber_count,
            "unlocked": subscriber_count >= 50,
        },
        {
            "id": "keyboard_warriors",
            "title": "Klavye Başındakiler",
            "tier": "bronze",
            "category": "engagement",
            "target": 25,
            "unit": "yorum",
            "current": total_comments,
            "unlocked": total_comments >= 25,
        },
        {
            "id": "first_like_wave",
            "title": "İlk Beğeni Dalgası",
            "tier": "bronze",
            "category": "engagement",
            "target": 100,
            "unit": "beğeni",
            "current": total_likes,
            "unlocked": total_likes >= 100,
        },
        {
            "id": "vertical_strip",
            "title": "Dikey Şerit",
            "tier": "bronze",
            "category": "shorts",
            "target": 10000,
            "unit": "Shorts izlenmesi",
            "current": shorts_views,
            "unlocked": shorts_count >= 10 and shorts_views >= 10000,
        },
        # Gumus Kupalar
        {
            "id": "viral_spark",
            "title": "Viral Kıvılcım",
            "tier": "silver",
            "category": "views",
            "target": 5000,
            "unit": "günlük izlenme",
            "current": max_daily_views,
            "unlocked": max_daily_views >= 5000,
        },
        {
            "id": "silver_threshold",
            "title": "Gümüş Eşik",
            "tier": "silver",
            "category": "community",
            "target": 500,
            "unit": "abone",
            "current": subscriber_count,
            "unlocked": subscriber_count >= 500,
        },
        {
            "id": "engagement_beast",
            "title": "Etkileşim Canavarı",
            "tier": "silver",
            "category": "engagement",
            "target": 8.0,
            "unit": "%",
            "current": engagement_rate,
            "unlocked": engagement_rate >= 8.0 and total_views >= 500,
        },
        {
            "id": "discussion_club",
            "title": "Tartışma Kulübü",
            "tier": "silver",
            "category": "engagement",
            "target": 250,
            "unit": "yorum",
            "current": total_comments,
            "unlocked": total_comments >= 250,
        },
        {
            "id": "screen_locked",
            "title": "Gözleri Ekrana Kilitledin",
            "tier": "silver",
            "category": "views",
            "target": 50000,
            "unit": "izlenme",
            "current": total_views,
            "unlocked": total_views >= 50000,
        },
        # Altin Kupalar
        {
            "id": "agenda_setter",
            "title": "Gündem Sensin!",
            "tier": "gold",
            "category": "views",
            "target": 25000,
            "unit": "günlük izlenme",
            "current": max_daily_views,
            "unlocked": max_daily_views >= 25000,
        },
        {
            "id": "thousands_club",
            "title": "Binler Kulübü",
            "tier": "gold",
            "category": "community",
            "target": 1000,
            "unit": "abone",
            "current": subscriber_count,
            "unlocked": subscriber_count >= 1000,
        },
        {
            "id": "shorts_phenom",
            "title": "Shorts Fenomeni",
            "tier": "gold",
            "category": "shorts",
            "target": 3000000,
            "unit": "Shorts izlenmesi",
            "current": shorts_views,
            "unlocked": shorts_views >= 3000000,
        },
        {
            "id": "marathon_runner",
            "title": "Maraton Koşucusu",
            "tier": "gold",
            "category": "views",
            "target": 3000,
            "unit": "saat",
            "current": watch_hours,
            "unlocked": watch_hours >= 3000,
        },
        # Platin Kupa (Para Kazanma)
        {
            "id": "youtube_partner",
            "title": "YouTube Partneri",
            "tier": "platinum",
            "category": "monetization",
            "target": 1,
            "unit": "YPP Onayı",
            "current": 1
            if (
                subscriber_count >= 1000
                and (watch_hours >= 4000 or shorts_views >= 10000000)
            )
            else 0,
            "unlocked": (
                subscriber_count >= 1000
                and (watch_hours >= 4000 or shorts_views >= 10000000)
            ),
        },
    ]

    bronze_unlocked = sum(
        1 for d in definitions if d["tier"] == "bronze" and d["unlocked"]
    )
    silver_unlocked = sum(
        1 for d in definitions if d["tier"] == "silver" and d["unlocked"]
    )
    gold_unlocked = sum(1 for d in definitions if d["tier"] == "gold" and d["unlocked"])
    platinum_unlocked = sum(
        1 for d in definitions if d["tier"] == "platinum" and d["unlocked"]
    )

    total_unlocked = (
        bronze_unlocked + silver_unlocked + gold_unlocked + platinum_unlocked
    )
    total_count = len(definitions)
    points = (
        bronze_unlocked * 15
        + silver_unlocked * 30
        + gold_unlocked * 90
        + platinum_unlocked * 300
    )
    level = max(1, (points // 60) + 1)

    return {
        "metrics": {
            "total_videos": total_videos,
            "total_views": total_views,
            "subscriber_count": subscriber_count,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "shorts_count": shorts_count,
            "shorts_views": shorts_views,
            "horizontal_count": horizontal_count,
            "horizontal_views": horizontal_views,
            "watch_hours": watch_hours,
            "max_daily_views": max_daily_views,
            "engagement_rate": engagement_rate,
        },
        "achievements": definitions,
        "summary": {
            "total": total_count,
            "unlocked_count": total_unlocked,
            "completion_percentage": round((total_unlocked / total_count) * 100)
            if total_count > 0
            else 0,
            "level": level,
            "bronze": {"total": 6, "unlocked": bronze_unlocked},
            "silver": {"total": 5, "unlocked": silver_unlocked},
            "gold": {"total": 4, "unlocked": gold_unlocked},
            "platinum": {"total": 1, "unlocked": platinum_unlocked},
            "is_monetized": platinum_unlocked > 0,
        },
    }


@router.get("/achievements/channel/{channel_id}")
async def get_channel_achievements(request: Request, channel_id: int) -> dict[str, Any]:
    """Kanalin YouTube basarimlarini ve kupa ilerlemesini hesaplar."""
    await ensure_channel_access(request, channel_id)

    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )

    settings = await effective_settings(request)
    service = YouTubeManageService(sessionmaker, settings)

    try:
        data = await service.list_channel_videos(channel_id)
    except YouTubeManageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc

    return _compute_achievements_payload(data)
