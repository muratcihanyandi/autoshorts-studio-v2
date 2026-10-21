"""Yayınlanmış medyanın temizliği (retention).

Herkese açık yapılmış videonun yerel dosyası, public_at + retention
süresi dolduğunda silinir: klip dosyası (rendered_clips + thumbnail);
kaynak video #confirmed ise yatay kaynak dosyası da (media_assets).
DB kayıtları her zaman kalır — kütüphanede dosyasız satır olarak
görünür; yalnız diskten dosya kalkar.

Retention politikası (settings.media_retention_days):
- -1: hiçbir zaman silme
-  0: herkese açık yapıldıktan hemen sonra
-  N: herkese açık yapıldıktan N gün sonra

Kayıp dosya süpürmesi (2026-10-21 canlı olay): dosyaları sistem
DIŞINDAN silinen videolar için asset satırı 'file_path'i dolu ama
dosya diskte yoktur; işler dosya hatasıyla düşer ve kuyruk kirlenir.
Saatlik süpürme bu videoları tespit eder ve UI'daki "Kaldır" ile
aynı düzgün temizliği uygular.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import PublishedVideo, RenderedClip, SourceVideo
from app.services.channel_service import record_event

# Bir süpürme turunda en fazla bu kadar video kaldırılır; devasa
# kayıplar (USB boşaltma gibi) saatlik turlara yayılır.
LOST_SWEEP_BATCH = 20


def _remove_file(path: str | None) -> bool:
    """Diskten dosyayı kaldır; yoksa/hata olursa sessizce atla."""
    if not path:
        return False
    try:
        file = Path(path)
        if file.is_file():
            file.unlink()
            return True
    except OSError:
        pass
    return False


def _file_exists(path: str | None, media_root: str | None) -> bool:
    """file_path diskte var mı? Göreceli yollar MEDIA_ROOT'a göre
    çözülür (retention/dikey temizliği bilinçli boş bıraktığı ''
    yollar buraya hiç gelmez)."""
    if not path:
        return False
    file = Path(path)
    if not file.is_absolute() and media_root:
        file = Path(media_root) / file
    try:
        return file.is_file()
    except OSError:
        return False


async def sweep_lost_source_files(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    batch: int = LOST_SWEEP_BATCH,
) -> dict:
    """Dosyası sistem dışından silinmiş videoları düzgünce kaldır.

    Tarama: file_path'i dolu ama diskte olmayan asset'ler. Yayın
    kaydı (public) taşıyan videolara dokunulmaz — retention temizliği
    onların dosyalarını kendi politikasıyla yönetir. Kaldırma, UI'daki
    tekil "Kaldır" ile aynı `remove_source_video` yolunu izler: işler
    iptal edilir, bağlı satırlar düşer, video 'excluded' kalır (kesif
    aynisini geri getirmez — dosyayi silen kullanicinin niyeti).
    """
    if not settings.media_root:
        return {"swept": 0, "skipped": True}
    from app.models import MediaAsset

    async with sessionmaker() as session:
        assets = (
            (
                await session.execute(
                    sa.select(
                        MediaAsset.id,
                        MediaAsset.source_video_id,
                        MediaAsset.file_path,
                    ).where(MediaAsset.file_path != "")
                )
            )
            .all()
        )
        lost_video_ids: list[int] = []
        for _asset_id, video_id, path in assets:
            if not _file_exists(path, settings.media_root):
                lost_video_ids.append(video_id)
        if not lost_video_ids:
            return {"swept": 0}
        # Yayınlanmış videolar süpürmeden muaftır.
        published = set(
            (
                await session.execute(
                    sa.select(PublishedVideo.source_video_id).where(
                        PublishedVideo.source_video_id.in_(lost_video_ids),
                        PublishedVideo.visibility == "public",
                    )
                )
            )
            .scalars()
            .all()
        )
        # Aslında candidate üzerinden yayınlanmış dikey klipler de var;
        # kaynak dosyası ölse bile kayıt korunmalı.
        from app.models import ClipCandidate

        candidate_published = set(
            (
                await session.execute(
                    sa.select(ClipCandidate.source_video_id)
                    .join(
                        PublishedVideo,
                        PublishedVideo.clip_candidate_id == ClipCandidate.id,
                    )
                    .where(
                        ClipCandidate.source_video_id.in_(lost_video_ids),
                        PublishedVideo.visibility == "public",
                    )
                )
            )
            .scalars()
            .all()
        )
        protected = published | candidate_published
        targets = [
            vid
            for vid in dict.fromkeys(lost_video_ids)
            if vid not in protected
        ][:batch]

    if not targets:
        return {"swept": 0, "protected": len(protected)}

    from app.services.video_removal import remove_source_video

    swept = 0
    errors = 0
    for video_id in targets:
        try:
            await remove_source_video(sessionmaker, settings, video_id)
            swept += 1
        except Exception:  # noqa: BLE001 - tek video hatasi turu durdurmasin
            errors += 1
            continue
    async with sessionmaker() as session:
        record_event(
            session,
            None,
            "media.lost_file_sweep",
            {"videos": swept, "errors": errors, "protected": len(protected)},
        )
        await session.commit()
    return {"swept": swept, "errors": errors, "protected": len(protected)}


async def cleanup_published_media(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict:
    """Dolumu gelmiş yayın dosyalarını temizle; istatistik döndür."""
    retention = settings.media_retention_days
    if retention is None or retention < 0:
        return {"cleaned": 0, "retention_days": retention, "skipped": True}
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention)
    cleaned = 0
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(PublishedVideo).where(
                        PublishedVideo.visibility == "public",
                        PublishedVideo.public_at.is_not(None),
                        PublishedVideo.public_at <= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            render = await _render_for_row(session, row)
            removed_paths: list[str] = []
            if render is not None:
                for field in ("file_path", "thumbnail_path"):
                    if _remove_file(getattr(render, field)):
                        removed_paths.append(str(getattr(render, field)))
                render.file_path = ""
                render.thumbnail_path = None
            # Kaynak confirmed ise (uretimi bitmis) kaynak dosyasi da.
            # Dikey klip satirlarinda bag render uzerinden cozulur.
            source_video_id = row.source_video_id or (
                render.source_video_id if render is not None else None
            )
            video = (
                await session.get(SourceVideo, source_video_id)
                if source_video_id is not None
                else None
            )
            if video is not None and video.status == "confirmed":
                from app.models import MediaAsset

                asset = (
                    (
                        await session.execute(
                            sa.select(MediaAsset).where(
                                MediaAsset.source_video_id == video.id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                if asset is not None and _remove_file(asset.file_path):
                    removed_paths.append(str(asset.file_path))
                    asset.file_path = ""
            if removed_paths:
                record_event(
                    session,
                    row.channel_id,
                    "media.cleaned",
                    {"published_video_id": row.id, "files": removed_paths},
                )
                cleaned += 1
        if cleaned:
            await session.commit()
    return {"cleaned": cleaned, "retention_days": retention}


async def _render_for_row(
    session: AsyncSession, row: PublishedVideo
) -> RenderedClip | None:
    """Yayın satırının dosyasını taşıyan render (dikey klip ya da
    yatay tam kesit)."""
    if row.clip_candidate_id is not None:
        statement = sa.select(RenderedClip).where(
            RenderedClip.clip_candidate_id == row.clip_candidate_id,
            RenderedClip.orientation == row.orientation,
        )
    elif row.source_video_id is not None:
        statement = sa.select(RenderedClip).where(
            RenderedClip.source_video_id == row.source_video_id,
            RenderedClip.clip_candidate_id.is_(None),
            RenderedClip.orientation == "horizontal",
        )
    else:
        return None
    return (
        (await session.execute(statement)).scalars().one_or_none()
    )


async def cleanup_vertical_source_files(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    source_video_id: int | None = None,
) -> dict:
    """Görev 2: dikey yönlü kaynakların yatay dosyalarını sil.

    output_orientation='vertical' olan bir kaynağın Shorts üretimi
    tamamlanınca (#confirmed) indirilen yatay video ve altyazı yan dosyası
    diskten kalkar; stokta yalnız dikey klipler kalır. DB kayıtları
    (media_assets, transcripts) durur — kütüphanede dosyasız satır olarak
    görünür, denetim izi korunur.
    """
    del settings  # politika ayarı yok: dikey kaynakta teslim anında silinir
    cleaned = 0
    async with sessionmaker() as session:
        from app.models import MediaAsset, SourceChannel, Transcript

        query = (
            sa.select(MediaAsset, SourceVideo, SourceChannel)
            .join(SourceVideo, MediaAsset.source_video_id == SourceVideo.id)
            .join(
                SourceChannel, SourceVideo.source_channel_id == SourceChannel.id
            )
            .where(
                SourceVideo.status == "confirmed",
                SourceChannel.output_orientation == "vertical",
                MediaAsset.file_path != "",
            )
        )
        if source_video_id is not None:
            query = query.where(MediaAsset.source_video_id == source_video_id)
        rows = (await session.execute(query)).all()
        for asset, video, source in rows:
            removed: list[str] = []
            if _remove_file(asset.file_path):
                removed.append(str(asset.file_path))
            asset.file_path = ""
            transcript = (
                (
                    await session.execute(
                        sa.select(Transcript).where(
                            Transcript.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if transcript is not None and transcript.raw_path:
                if _remove_file(transcript.raw_path):
                    removed.append(str(transcript.raw_path))
                transcript.raw_path = None
            if removed:
                record_event(
                    session,
                    source.channel_id,
                    "media.vertical_source_cleaned",
                    {
                        "source_video_id": video.id,
                        "files": removed,
                    },
                )
                cleaned += 1
        if cleaned:
            await session.commit()
    return {"cleaned": cleaned}
