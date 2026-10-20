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
        files_removed = 0
        assets = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id == source_video_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for asset in assets:
            files_removed += _remove_file(asset.file_path, settings.media_root)
            if asset.file_path:
                base = Path(asset.file_path)
                for suffix in (".vtt", ".srt"):
                    files_removed += _remove_file(
                        str(base.with_suffix(suffix)), settings.media_root
                    )
        renders = (
            (
                await session.execute(
                    sa.select(RenderedClip).where(
                        RenderedClip.source_video_id == source_video_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for render in renders:
            files_removed += _remove_file(render.file_path, settings.media_root)
            files_removed += _remove_file(render.thumbnail_path, settings.media_root)

        # 2) Sirada bekleyen ilgili isler iptal edilir (ayni oturumda
        # toplu guncelleme: ayri servis oturumu SQLite'ta kilitlenir).
        candidate_ids = set(
            (
                await session.execute(
                    sa.select(ClipCandidate.id).where(
                        ClipCandidate.source_video_id == source_video_id
                    )
                )
            )
            .scalars()
            .all()
        )
        asset_ids = {asset.id for asset in assets}
        queued = (
            (
                await session.execute(
                    sa.select(Job).where(
                        Job.status == "queued",
                        Job.job_type.in_(VIDEO_JOB_TYPES),
                    )
                )
            )
            .scalars()
            .all()
        )
        cancel_ids = []
        for job in queued:
            payload = job.payload or {}
            if (
                payload.get("source_video_id") == source_video_id
                or payload.get("clip_candidate_id") in candidate_ids
                or payload.get("media_asset_id") in asset_ids
            ):
                cancel_ids.append(job.id)
        if cancel_ids:
            await session.execute(
                sa.update(Job)
                .where(Job.id.in_(cancel_ids))
                .values(status="cancelled")
            )
        jobs_cancelled = len(cancel_ids)

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
