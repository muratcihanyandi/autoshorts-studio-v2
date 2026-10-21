"""Medya kütüphanesi toplu klip eylemleri (kullanıcı isteği
2026-10-21, Görev 4): seçilen hazır klipleri toplu herkese açma,
gizliye alma ve kalıcı kaldırma.

Tekil yollar zaten mevcut (remove_rendered_clip, publishing
make_public); buradaki iş batch orkestrasyonu ve kısmi başarı
raporu — bir klibin YouTube hatası tüm grubu durdurmaz, o klip
'error' olarak raporlanır ve kalanlar işlenir. Gizliye alma
published_at/public_at damgalarını temizler: klip "yüklenmiş ama
gizli" durumuna döner, günlük yayın sayıçlarından düşer; tekrar
herkese açıldığında yeni damga yazılır.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import PublishedVideo, RenderedClip
from app.services.channel_service import record_event
from app.services.oauth_service import OAuthService
from app.services.settings_service import SettingsService
from app.services.youtube_upload import YouTubeUploadClient

# Tek istekte işlenebilecek en fazla klip (UI listesi zaten sayfalı;
# sonsuz döngü/aşırı yük koruması).
BULK_LIMIT = 50

ACTIONS = ("delete", "public", "private")


class ClipActionError(Exception):
    """Kullanıcıya Türkçe mesajla taşınan toplu eylem hatası."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


async def _published_row_for_render(
    session: AsyncSession, render: RenderedClip
) -> PublishedVideo | None:
    """Render'ın yayınlama kaydı: dikeyde aday üzerinden, yatay tam
    kesitte kaynak videosu üzerinden (published satırındaki aynı
    eşleşme mantığı)."""
    if render.clip_candidate_id is not None:
        statement = sa.select(PublishedVideo).where(
            PublishedVideo.clip_candidate_id == render.clip_candidate_id
        )
    elif render.source_video_id is not None:
        statement = sa.select(PublishedVideo).where(
            PublishedVideo.source_video_id == render.source_video_id,
            PublishedVideo.clip_candidate_id.is_(None),
        )
    else:
        return None
    return (
        (await session.execute(statement)).scalars().one_or_none()
    )


async def _set_visibility(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    render_id: int,
    target: str,
    http: httpx.AsyncClient,
) -> dict[str, Any]:
    """Bir klibin YouTube görünürlüğünü değiştir ve kaydı damgala."""
    async with sessionmaker() as session:
        render = await session.get(RenderedClip, render_id)
        if render is None:
            return {
                "render_id": render_id,
                "status": "error",
                "note": "Klip bulunamadı.",
            }
        pub = await _published_row_for_render(session, render)
        if pub is None or not pub.youtube_video_id:
            return {
                "render_id": render_id,
                "status": "skipped",
                "note": "YouTube'a henüz yüklenmemiş; görünürlük değiştirilemez.",
            }
        if pub.status != "verified":
            return {
                "render_id": render_id,
                "status": "skipped",
                "note": "Yükleme henüz doğrulanmadı.",
            }
        if pub.visibility == target:
            label = "herkese açık" if target == "public" else "gizli"
            return {
                "render_id": render_id,
                "status": "skipped",
                "note": f"Zaten {label}.",
            }
        channel_id = pub.channel_id
        youtube_video_id = pub.youtube_video_id

    try:
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        oauth = OAuthService(sessionmaker, effective)
        token = await oauth.access_token(channel_id, http=http)
        uploader = YouTubeUploadClient(token)
        await uploader.set_privacy(http, youtube_video_id, target)
        status = await uploader.fetch_status(http, youtube_video_id)
        if status.privacy_status != target:
            return {
                "render_id": render_id,
                "status": "error",
                "note": (
                    "Görünürlük doğrulanamadı "
                    f"({status.privacy_status!r})."
                ),
            }
    except Exception as exc:  # noqa: BLE001 - klibe ozel hata
        return {
            "render_id": render_id,
            "status": "error",
            "note": f"{type(exc).__name__}: {exc}"[:300],
        }

    now = datetime.now(UTC)
    async with sessionmaker() as session:
        row = (
            (await session.execute(
                sa.select(PublishedVideo).where(
                    PublishedVideo.youtube_video_id == youtube_video_id
                )
            ))
            .scalars()
            .one_or_none()
        )
        if row is None:
            return {
                "render_id": render_id,
                "status": "error",
                "note": "Yayın kaydı bu arada kaldırıldı.",
            }
        row.visibility = target
        if target == "public":
            # Zamanlı yayın adımıyla aynı semantik (make_public).
            row.public_at = now
            row.published_at = now
        else:
            # Gizliye alma: yayın sayıçlarından düşsün; tekrar
            # açılırsa yeni damga yazılır.
            row.public_at = None
            row.published_at = None
        record_event(
            session,
            channel_id,
            "publish.public" if target == "public" else "publish.private",
            {"youtube_video_id": youtube_video_id},
        )
        await session.commit()
    return {
        "render_id": render_id,
        "status": "ok",
        "visibility": target,
    }


async def bulk_clip_action(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    render_ids: list[int],
    action: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Seçilen klipler için toplu eylem. Silme tekil kaldırma
    yolunu (YouTube önce, sonra yerel) her klibe uygular; görünürlük
    değişikliği doğrulanmış yükleme ister. Sonuç liste olarak döner:
    status 'ok' | 'skipped' | 'error'."""
    if action not in ACTIONS:
        raise ClipActionError(
            "Eylem 'delete', 'public' ya da 'private' olmalı."
        )
    unique_ids = list(dict.fromkeys(render_ids))
    if not unique_ids:
        raise ClipActionError("Klip seçilmedi.")
    if len(unique_ids) > BULK_LIMIT:
        raise ClipActionError(
            f"Tek seferde en fazla {BULK_LIMIT} klip işlenebilir."
        )

    from app.services.video_removal import remove_rendered_clip

    owned = http is None
    client = http if http is not None else httpx.AsyncClient(timeout=120.0)
    results: list[dict[str, Any]] = []
    try:
        for render_id in unique_ids:
            if action == "delete":
                try:
                    outcome = await remove_rendered_clip(
                        sessionmaker, settings, render_id, http=client
                    )
                    if outcome.get("skipped"):
                        results.append(
                            {
                                "render_id": render_id,
                                "status": "skipped",
                                "note": "Klip zaten kaldırılmış.",
                            }
                        )
                    else:
                        results.append(
                            {
                                "render_id": render_id,
                                "status": "ok",
                                "note": (
                                    f"{outcome['files_removed']} dosya silindi"
                                ),
                            }
                        )
                except Exception as exc:  # noqa: BLE001 - klibe ozel hata
                    message = str(exc) or type(exc).__name__
                    results.append(
                        {
                            "render_id": render_id,
                            "status": "error",
                            "note": message[:300],
                        }
                    )
            else:
                results.append(
                    await _set_visibility(
                        sessionmaker, settings, render_id, action, client
                    )
                )
    finally:
        if owned:
            await client.aclose()

    return {
        "action": action,
        "total": len(unique_ids),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
