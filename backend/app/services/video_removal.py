"""Kaynak video kaldırma (kullanıcı isteği 2026-10-20): arayüzden
seçilen ya da kalıcı başarısız videoları sistemden temizler.

Davranış: diskteki dosyalar silinir (indirme + altyazı yan dosyaları +
render çıktıları + kapakler), varlık/aday/render/metaveri satırları
düşer, video 'excluded' yapılır. Manuel hariç olduğu için kural
değişikliklerinde reapply asla geri getirmez ve varsayılan kütüphane
görünümünde kaybolur. Sırada bekleyen ilgili işler iptal edilir;
yayınlama kayıtları (varsa) korunur.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    ClipCandidate,
    ClipMetadata,
    CorrectedTranscript,
    Job,
    MediaAsset,
    MediaInspection,
    PlanningDecision,
    RenderedClip,
    SourceVideo,
    Transcript,
)
from app.services.channel_service import record_event

# Kaldırma sırasında iptal edilen, videoya bağlanabilen iş türleri.
VIDEO_JOB_TYPES = (
    "media_process",
    "hype_evaluate",
    "clip_render",
    "clip_render_full_cut",
    "metadata_generate",
    "subtitle_correct",
    "publish_full_cut",
)


class VideoRemovalError(Exception):
    """Kullanıcıya Türkçe mesajla taşınan kaldırma hatası."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _remove_file(path: str | None, media_root: str | None) -> bool:
    """Dosyayı diskten sil; göreceli yollar MEDIA_ROOT'a göre çözülür
    (kapak yolları göreceli kaydedilir)."""
    if not path:
        return False
    try:
        target = Path(path)
        if not target.is_absolute() and media_root:
            target = Path(media_root) / target
        if target.is_file():
            target.unlink()
            return True
    except OSError:
        pass
    return False


async def _video_cleanup_targets(
    session: AsyncSession, source_video_ids: list[int]
) -> tuple[list[MediaAsset], list[RenderedClip], set[int], set[int]]:
    """Videoların varlık/render/aday kimliklerini toplar: dosya silme ve
    iş eşleştirmesi için tek ortak okuma."""
    assets = (
        (
            await session.execute(
                sa.select(MediaAsset).where(
                    MediaAsset.source_video_id.in_(source_video_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    renders = (
        (
            await session.execute(
                sa.select(RenderedClip).where(
                    RenderedClip.source_video_id.in_(source_video_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    candidate_ids = set(
        (
            await session.execute(
                sa.select(ClipCandidate.id).where(
                    ClipCandidate.source_video_id.in_(source_video_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    asset_ids = {asset.id for asset in assets}
    return list(assets), list(renders), candidate_ids, asset_ids


def _remove_video_files(
    assets: list[MediaAsset],
    renders: list[RenderedClip],
    media_root: str | None,
) -> int:
    """İndirme + yan altyazı + render çıktısı + kapak dosyalarını sil."""
    removed = 0
    for asset in assets:
        removed += _remove_file(asset.file_path, media_root)
        if asset.file_path:
            base = Path(asset.file_path)
            for suffix in (".vtt", ".srt"):
                removed += _remove_file(
                    str(base.with_suffix(suffix)), media_root
                )
    for render in renders:
        removed += _remove_file(render.file_path, media_root)
        removed += _remove_file(render.thumbnail_path, media_root)
    return removed


async def _cancel_video_jobs(
    session: AsyncSession,
    source_video_ids: list[int],
    candidate_ids: set[int],
    asset_ids: set[int],
) -> dict[str, int]:
    """Videoya bağlanabilen etkin işleri iptal eder.

    Siradakiler aninda 'cancelled' olur; kosanlar 'cancelling' isareti
    alir ve worker sonucu yazarken iptale oturur (succeed/fail ikisi de
    isareti onurlandirir). Ayni oturumda toplu guncelleme: ayri servis
    oturumu SQLite'ta kilitlenir."""
    active = (
        (
            await session.execute(
                sa.select(Job).where(
                    Job.status.in_(("queued", "running", "cancelling")),
                    Job.job_type.in_(VIDEO_JOB_TYPES),
                )
            )
        )
        .scalars()
        .all()
    )
    cancel_now: list[int] = []
    marking: list[int] = []
    for job in active:
        payload = job.payload or {}
        if not (
            payload.get("source_video_id") in source_video_ids
            or payload.get("clip_candidate_id") in candidate_ids
            or payload.get("media_asset_id") in asset_ids
        ):
            continue
        if job.status == "queued":
            cancel_now.append(job.id)
        else:
            marking.append(job.id)
    if cancel_now:
        await session.execute(
            sa.update(Job)
            .where(Job.id.in_(cancel_now))
            .values(status="cancelled")
        )
    if marking:
        await session.execute(
            sa.update(Job).where(Job.id.in_(marking)).values(status="cancelling")
        )
    return {"cancelled": len(cancel_now), "cancelling": len(marking)}


async def remove_source_video(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    source_video_id: int,
) -> dict[str, Any]:
    async with sessionmaker() as session:
        video = await session.get(SourceVideo, source_video_id)
        if video is None:
            raise VideoRemovalError("Kaynak video bulunamadi.", 404)
        channel_id: int | None = None
        from app.models import SourceChannel

        source = await session.get(
            SourceChannel, video.source_channel_id
        )
        if source is not None:
            channel_id = source.channel_id

        # 1) Dosyalar: indirme + yan altyazilar + render ciktilari.
        assets, renders, candidate_ids, asset_ids = await _video_cleanup_targets(
            session, [source_video_id]
        )
        files_removed = _remove_video_files(
            assets, renders, settings.media_root
        )

        # 2) Sirada bekleyen ilgili isler iptal edilir; kosanlar
        #    'cancelling' isareti alir (worker sonucu yazarken oturur).
        cancel = await _cancel_video_jobs(
            session, [source_video_id], candidate_ids, asset_ids
        )
        jobs_cancelled = cancel["cancelled"] + cancel["cancelling"]

        # 3) Satirlar: transkript, inceleme, varlik, metaveri, render,
        #    aday ve planlama karari. Video 'excluded' olarak kalir
        #    (kesif dedupe'i ayni videoyu tekrar eklemez).
        await session.execute(
            sa.delete(CorrectedTranscript).where(
                CorrectedTranscript.media_asset_id.in_(asset_ids)
            )
        )
        await session.execute(
            sa.delete(MediaInspection).where(
                MediaInspection.media_asset_id.in_(asset_ids)
            )
        )
        await session.execute(
            sa.delete(Transcript).where(
                Transcript.media_asset_id.in_(asset_ids)
            )
        )
        await session.execute(
            sa.delete(MediaAsset).where(
                MediaAsset.source_video_id == source_video_id
            )
        )
        await session.execute(
            sa.delete(ClipMetadata).where(
                sa.or_(
                    ClipMetadata.source_video_id == source_video_id,
                    ClipMetadata.clip_candidate_id.in_(candidate_ids),
                )
            )
        )
        await session.execute(
            sa.delete(RenderedClip).where(
                sa.or_(
                    RenderedClip.source_video_id == source_video_id,
                    RenderedClip.clip_candidate_id.in_(candidate_ids),
                )
            )
        )
        await session.execute(
            sa.delete(ClipCandidate).where(
                ClipCandidate.source_video_id == source_video_id
            )
        )
        await session.execute(
            sa.delete(PlanningDecision).where(
                PlanningDecision.source_video_id == source_video_id
            )
        )
        video.status = "excluded"
        if channel_id is not None:
            record_event(
                session,
                channel_id,
                "media.video_removed",
                {
                    "source_video_id": source_video_id,
                    "files_removed": files_removed,
                    "jobs_cancelled": jobs_cancelled,
                },
            )
        await session.commit()

    return {
        "source_video_id": source_video_id,
        "status": "excluded",
        "files_removed": files_removed,
        "jobs_cancelled": jobs_cancelled,
    }


async def remove_source_videos(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    source_channel_id: int,
) -> dict[str, Any]:
    """Kaynak kanal silinmeden önce tüm videolarının disk ve kuyruk
    temizliğini yapar (2026-10-21 canlı olay: FK cascade satırları
    düşürür ama dosyalar yetim kalır, koşan işler hayalet'e döner).

    Satır temizliği bilinçli olarak burada yapılmaz: kaynak satırı
    silindiğinde cascade zaten tüm ağacı düşürür."""
    async with sessionmaker() as session:
        video_ids = list(
            (
                await session.execute(
                    sa.select(SourceVideo.id).where(
                        SourceVideo.source_channel_id == source_channel_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not video_ids:
            return {
                "videos": 0,
                "files_removed": 0,
                "jobs_cancelled": 0,
            }
        assets, renders, candidate_ids, asset_ids = await _video_cleanup_targets(
            session, video_ids
        )
        files_removed = _remove_video_files(
            assets, renders, settings.media_root
        )
        cancel = await _cancel_video_jobs(
            session, video_ids, candidate_ids, asset_ids
        )
        await session.commit()
    return {
        "videos": len(video_ids),
        "files_removed": files_removed,
        "jobs_cancelled": cancel["cancelled"] + cancel["cancelling"],
    }


async def remove_rendered_clip(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    render_id: int,
    *,
    http: Any = None,
) -> dict[str, Any]:
    """Hazır klibi kaldırır (kullanıcı isteği 2026-10-21): önce
    YouTube'daki gizli video silinir, sonra yerel dosyalar.

    YouTube silinemediyse HİÇBİR ŞEY silinmez — yerel video korunur.
    Render satırı 'removed' mezartaşı olur: render/yükleme/metaveri
    beslemeleri status='rendered' ister, dolayısıyla klip yeniden
    üretilmez, yüklenmez; aday ve hype seçimi aynen kalır."""
    import httpx

    from app.models import PublishedVideo, RenderedClip
    from app.services.oauth_service import OAuthService
    from app.services.settings_service import SettingsService
    from app.services.youtube_upload import YouTubeUploadClient

    async with sessionmaker() as session:
        render = await session.get(RenderedClip, render_id)
        if render is None:
            raise VideoRemovalError("Klip bulunamadi.", 404)
        if render.status == "removed":
            return {
                "render_id": render_id,
                "status": "removed",
                "youtube_deleted": [],
                "files_removed": 0,
                "jobs_cancelled": 0,
                "skipped": True,
            }
        candidate_id = render.clip_candidate_id
        source_video_id = render.source_video_id
        file_path = render.file_path
        thumbnail_path = render.thumbnail_path

        if candidate_id is not None:
            pub_rows = (
                (
                    await session.execute(
                        sa.select(PublishedVideo).where(
                            PublishedVideo.clip_candidate_id == candidate_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        elif source_video_id is not None:
            pub_rows = (
                (
                    await session.execute(
                        sa.select(PublishedVideo).where(
                            PublishedVideo.source_video_id
                            == source_video_id,
                            PublishedVideo.clip_candidate_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        else:
            pub_rows = []
        youtube_ids = [
            row.youtube_video_id
            for row in pub_rows
            if row.youtube_video_id
        ]
        channel_id = pub_rows[0].channel_id if pub_rows else None

    # 1) YouTube tarafı önce: gizli yüklenmişse oradan sil.
    if youtube_ids and channel_id is not None:
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        oauth = OAuthService(sessionmaker, effective)
        owned = http is None
        client = http if http is not None else httpx.AsyncClient()
        try:
            token = await oauth.access_token(channel_id, http=client)
            uploader = YouTubeUploadClient(token)
            for video_id in youtube_ids:
                await uploader.delete_video(client, video_id)
        except Exception as exc:  # noqa: BLE001 - YouTube silinemedi
            raise VideoRemovalError(
                f"YouTube videosu silinemedi, yerel klip korundu: {exc}",
                502,
            ) from exc
        finally:
            if owned:
                await client.aclose()

    # 2) Yerel dosyalar.
    files_removed = _remove_file(file_path, settings.media_root)
    files_removed += _remove_file(thumbnail_path, settings.media_root)

    # 3) Satirlar: render mezartasi, yayin kayitlari duser, siradaki
    #    isler iptal edilir.
    async with sessionmaker() as session:
        row = await session.get(RenderedClip, render_id)
        row.status = "removed"
        if candidate_id is not None:
            await session.execute(
                sa.delete(PublishedVideo).where(
                    PublishedVideo.clip_candidate_id == candidate_id
                )
            )
        elif source_video_id is not None:
            await session.execute(
                sa.delete(PublishedVideo).where(
                    PublishedVideo.source_video_id == source_video_id,
                    PublishedVideo.clip_candidate_id.is_(None),
                )
            )
        if candidate_id is not None:
            job_types = (
                "clip_render",
                "metadata_generate",
                "publish_clip",
                "subtitle_correct",
            )
        else:
            job_types = (
                "clip_render_full_cut",
                "publish_full_cut",
                "metadata_generate",
            )
        queued = (
            (
                await session.execute(
                    sa.select(Job).where(
                        Job.status == "queued",
                        Job.job_type.in_(job_types),
                    )
                )
            )
            .scalars()
            .all()
        )
        cancel_ids = []
        for job in queued:
            payload = job.payload or {}
            if candidate_id is not None:
                if payload.get("clip_candidate_id") == candidate_id:
                    cancel_ids.append(job.id)
            elif payload.get("source_video_id") == source_video_id:
                cancel_ids.append(job.id)
        if cancel_ids:
            await session.execute(
                sa.update(Job)
                .where(Job.id.in_(cancel_ids))
                .values(status="cancelled")
            )
        jobs_cancelled = len(cancel_ids)
        if channel_id is not None:
            record_event(
                session,
                channel_id,
                "media.clip_removed",
                {
                    "render_id": render_id,
                    "youtube_deleted": youtube_ids,
                    "files_removed": files_removed,
                    "jobs_cancelled": jobs_cancelled,
                },
            )
        await session.commit()

    return {
        "render_id": render_id,
        "status": "removed",
        "youtube_deleted": youtube_ids,
        "files_removed": files_removed,
        "jobs_cancelled": jobs_cancelled,
    }
