"""Stage-gated media pipeline orchestrator (M7).

One media_process job runs one planned source video through:
download -> inspect -> transcript -> analysis -> candidates.

Every stage commits its own progress on the media_assets row, so a
failed job retried by the queue (M6 heartbeat/retry machinery) resumes
at the failed stage instead of redownloading. 'stage' names the next
pending stage; status='processed' marks the pipeline done. Originals
stay in downloads/ (local imports are copied, never moved) and each
stage appends a channel audit event.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    ClipCandidate,
    MediaAsset,
    MediaInspection,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.services.channel_service import record_event
from app.services.clip_candidates import (
    find_near_duplicate,
    generate_candidates,
)
from app.services.media_analysis import (
    audio_rms_windows,
    analysis_timeout,
    detect_scene_changes,
    detect_silence,
    intro_outro_from_silences,
)
from app.services.media_download import (
    LocalImportAdapter,
    MediaSourceAdapter,
    YtDlpAdapter,
)
from app.services.media_probe import integrity_ok, probe_media, sha256_file
from app.services.media_storage import media_subdir
from app.services.media_transcript import (
    find_sidecar,
    parse_sidecar_text,
    transcript_text_in_range,
)

STAGES = ("download", "inspect", "transcript", "analysis", "candidates")
_STAGE_STATUS = {
    "download": "downloaded",
    "inspect": "inspected",
    "transcript": "transcribed",
    "analysis": "analyzed",
    "candidates": "processed",
}


class MediaPipelineError(Exception):
    """Pipeline failure with a user-facing Turkish message."""


class MediaPipelineService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        youtube_adapter: MediaSourceAdapter | None = None,
        download_lock: Any | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        # Testler sahte youtube adaptoru enjekte edebilir.
        self._youtube_adapter = youtube_adapter
        self._download_lock = download_lock

    async def run(
        self, source_video_id: int, import_path: str | None = None
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None:
                raise MediaPipelineError("Kaynak video bulunamadi.")
            source = await session.get(SourceChannel, video.source_channel_id)
            if source is None or source.permission_status != "authorized":
                raise MediaPipelineError(
                    "Kaynak kanal yetkili degil; medya isleme reddedildi."
                )
            channel_id = source.channel_id
            youtube_video_id = video.youtube_video_id
            if video.status == "processed":
                return {"source_video_id": source_video_id, "skipped": True}
            if video.status == "excluded":
                # Kural (ör. yalnız tepki videoları) videoyu hariç tuttu:
                # iş başlamadan sessizce kapanır, indirme yapılmaz.
                return {"source_video_id": source_video_id, "skipped": True}

        asset_id = await self._ensure_asset(
            source_video_id, import_path is not None
        )
        # Acik import_path her zaman yeni giris demektir: yarim kalmis
        # bir varlikta indirme asamasi bastan kosar (bozuk dosya
        # uzerinde tekrar deneme hatasi onlenir).
        if import_path is not None:
            await self._reset_to_download(asset_id)
        excluded_midway = False
        while True:
            async with self._sessionmaker() as session:
                asset = await session.get(MediaAsset, asset_id)
                stage = asset.stage
                done = asset.status == "processed"
                # Kural videoyu iş ortasında hariç tuttuysa (ör. tepkime
                # kuralı açıldı): aşama ilerletilmeden durulur.
                current = await session.get(SourceVideo, source_video_id)
                if current is not None and current.status == "excluded":
                    excluded_midway = True
            if excluded_midway or done or stage not in STAGES:
                break
            handler = getattr(self, f"_stage_{stage}")
            try:
                await handler(
                    asset_id,
                    channel_id,
                    source_video_id,
                    youtube_video_id,
                    import_path,
                )
            except MediaPipelineError as exc:
                await self._mark_failed(asset_id, exc)
                raise
            except Exception as exc:
                await self._mark_failed(asset_id, exc)
                raise MediaPipelineError(
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            import_path = None  # yalnizca ilk denemede kullanilir

        if excluded_midway:
            return {"source_video_id": source_video_id, "skipped": True}

        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is not None and video.status == "planned":
                video.status = "processed"
                await session.commit()
        return {"source_video_id": source_video_id, "processed": True}

    # --- yardimcilar ---

    async def _ensure_asset(
        self, source_video_id: int, local_import: bool
    ) -> int:
        async with self._sessionmaker() as session:
            asset = (
                (
                    await session.execute(
                        sa.select(MediaAsset).where(
                            MediaAsset.source_video_id == source_video_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if asset is None:
                asset = MediaAsset(
                    source_video_id=source_video_id,
                    origin="local_import" if local_import else "youtube",
                    file_path="",  # indirme asamasinda dolar
                )
                session.add(asset)
                await session.commit()
            return asset.id

    async def _reset_to_download(self, asset_id: int) -> None:
        """Tamamlanmamis varligi indirme asamasina dondur (M12)."""
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            if asset is None or asset.status == "processed":
                return
            if asset.stage != "download":
                asset.stage = "download"
                asset.status = "downloading"
                asset.last_error = None
            await session.commit()

    async def _mark_failed(self, asset_id: int, exc: Exception) -> None:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            if asset is None:
                return
            asset.status = "failed"
            asset.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            await session.commit()

    @staticmethod
    def _complete_stage(asset: MediaAsset, stage: str) -> None:
        asset.status = _STAGE_STATUS[stage]
        next_index = STAGES.index(stage) + 1
        if next_index < len(STAGES):
            asset.stage = STAGES[next_index]
        # son asamada stage yerinde kalir; status='processed' donguyu kapatir

    # --- asamalar ---

    async def _stage_download(
        self,
        asset_id: int,
        channel_id: int,
        source_video_id: int,
        youtube_video_id: str,
        import_path: str | None,
    ) -> None:
        if not self._settings.media_root:
            raise MediaPipelineError(
                "MEDIA_ROOT yapilandirilmamis; indirme hedefi yok."
            )
        from app.services.job_service import JobService

        dest_dir = media_subdir(self._settings.media_root, "downloads")
        if not JobService(self._sessionmaker, self._settings).disk_ok(
            str(dest_dir)
        ):
            raise MediaPipelineError("Disk alani yetersiz; indirme durduruldu.")

        if import_path:
            adapter: MediaSourceAdapter = LocalImportAdapter(import_path)
        elif self._youtube_adapter is not None:
            adapter = self._youtube_adapter
        else:
            adapter = YtDlpAdapter(self._settings)

        # Sirali indirme: ayni anda tek indirme (kabul kriteri).
        if self._download_lock is not None:
            async with self._download_lock:
                result = await adapter.fetch(
                    source_video_id, youtube_video_id, dest_dir
                )
        else:
            result = await adapter.fetch(
                source_video_id, youtube_video_id, dest_dir
            )

        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            asset.file_path = str(result.path)
            asset.file_bytes = result.file_bytes
            asset.origin = result.origin
            self._complete_stage(asset, "download")
            record_event(
                session,
                channel_id,
                "media.download",
                {
                    "source_video_id": source_video_id,
                    "origin": result.origin,
                    "file_bytes": result.file_bytes,
                },
            )
            await session.commit()

    async def _stage_inspect(
        self,
        asset_id: int,
        channel_id: int,
        source_video_id: int,
        youtube_video_id: str,
        import_path: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            media_path = asset.file_path
        if not media_path or not Path(media_path).is_file():
            raise MediaPipelineError("Indirilen medya dosyasi bulunamadi.")

        try:
            inspection = await probe_media(
                self._settings.ffprobe_bin, media_path
            )
            digest = await sha256_file(media_path)
        except Exception as exc:
            raise MediaPipelineError(f"Medya dogrulanamadi: {exc}") from exc
        if not integrity_ok(inspection):
            raise MediaPipelineError(
                "Medya butunluk kontrolunu gecemedi (video akisi veya sure)."
            )

        async with self._sessionmaker() as session:
            existing = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if existing is None:
                session.add(
                    MediaInspection(
                        media_asset_id=asset_id,
                        duration_seconds=inspection.duration_seconds,
                        width=inspection.width,
                        height=inspection.height,
                        fps=inspection.fps,
                        video_codec=inspection.video_codec,
                        audio_codec=inspection.audio_codec,
                        has_audio=inspection.has_audio,
                        format_name=inspection.format_name,
                        raw={
                            "duration": inspection.duration_seconds,
                            "codec": inspection.video_codec,
                        },
                    )
                )
            asset = await session.get(MediaAsset, asset_id)
            asset.sha256 = digest
            self._complete_stage(asset, "inspect")
            record_event(
                session,
                channel_id,
                "media.inspect",
                {
                    "source_video_id": source_video_id,
                    "duration_seconds": inspection.duration_seconds,
                    "width": inspection.width,
                    "height": inspection.height,
                    "has_audio": inspection.has_audio,
                },
            )
            await session.commit()

    async def _stage_transcript(
        self,
        asset_id: int,
        channel_id: int,
        source_video_id: int,
        youtube_video_id: str,
        import_path: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            media_path = asset.file_path
            origin = asset.origin

        sidecar = find_sidecar(media_path) if media_path else None
        segments: list[dict] = []
        raw_path: str | None = None
        source_kind = "sidecar" if origin == "local_import" else "auto_caption"
        whisper_used = False
        whisper_error: str | None = None
        if sidecar is not None:
            text = await asyncio.to_thread(
                sidecar.read_text, encoding="utf-8", errors="replace"
            )
            segments = parse_sidecar_text(text)
            raw_path = str(sidecar)
        elif self._settings.transcription_method == "whisper" and media_path:
            # Altyazi yok: yerel Whisper fallback (python -m whisper;
            # kurulum Ayarlar'daki 'Indir ve Kur' ile yapilir).
            from app.services.media_storage import media_subdir
            from app.services.media_transcript import (
                TranscriptError,
                WhisperTranscriber,
            )
            from app.services.whisper_install import subprocess_env

            tmp_dir = media_subdir(self._settings.media_root, "tmp")
            try:
                segments = await WhisperTranscriber(
                    env=subprocess_env(self._settings)
                ).transcribe(
                    media_path,
                    tmp_dir,
                    model=self._settings.whisper_model,
                    language=self._settings.whisper_language,
                )
                source_kind = "whisper"
                whisper_used = True
            except TranscriptError as exc:
                # Transkript uretilemedi: is kaybolmaz, hata kayda gecer
                # ve hat bicimi (enerji/sahne) uzerinden devam eder.
                whisper_error = str(exc)

        async with self._sessionmaker() as session:
            existing = (
                (
                    await session.execute(
                        sa.select(Transcript).where(
                            Transcript.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if existing is None and segments:
                session.add(
                    Transcript(
                        media_asset_id=asset_id,
                        source=source_kind,
                        segment_count=len(segments),
                        segments=segments,
                        raw_path=raw_path,
                    )
                )
            asset = await session.get(MediaAsset, asset_id)
            self._complete_stage(asset, "transcript")
            record_event(
                session,
                channel_id,
                "media.transcript",
                {
                    "source_video_id": source_video_id,
                    "segment_count": len(segments),
                    "found": sidecar is not None,
                    "whisper_used": whisper_used,
                    "whisper_error": whisper_error,
                },
            )
            await session.commit()

    async def _stage_analysis(
        self,
        asset_id: int,
        channel_id: int,
        source_video_id: int,
        youtube_video_id: str,
        import_path: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            media_path = asset.file_path
            inspection = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            # Uzun VOD'lar icin analiz zamani asimi sure ile oranlanir;
            # sabit 600 sn saatlerce suren yayinlarda yetismiyordu.
            budget = analysis_timeout(
                inspection.duration_seconds if inspection else None
            )

        silences = await detect_silence(
            self._settings.ffmpeg_bin,
            media_path,
            noise_db=self._settings.silence_noise_db,
            min_seconds=self._settings.silence_min_seconds,
            timeout=budget,
        )
        scenes = await detect_scene_changes(
            self._settings.ffmpeg_bin,
            media_path,
            threshold=self._settings.scene_threshold,
            timeout=budget,
        )
        energy = await audio_rms_windows(
            self._settings.ffmpeg_bin, media_path, timeout=budget
        )

        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            asset.analysis = {
                "silences": [list(pair) for pair in silences],
                "scene_changes": scenes,
                "energy_windows": [round(v, 2) for v in energy],
            }
            self._complete_stage(asset, "analysis")
            record_event(
                session,
                channel_id,
                "media.analysis",
                {
                    "source_video_id": source_video_id,
                    "silence_runs": len(silences),
                    "scene_changes": len(scenes),
                },
            )
            await session.commit()

    async def _stage_candidates(
        self,
        asset_id: int,
        channel_id: int,
        source_video_id: int,
        youtube_video_id: str,
        import_path: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, asset_id)
            analysis = asset.analysis or {}
            inspection = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            transcript = (
                (
                    await session.execute(
                        sa.select(Transcript).where(
                            Transcript.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            duration = inspection.duration_seconds if inspection else 0.0
            segments = transcript.segments if transcript else []

        silences = [tuple(pair) for pair in analysis.get("silences", [])]
        intro_end, outro_start = intro_outro_from_silences(silences, duration)
        specs = generate_candidates(
            duration,
            intro_end=intro_end,
            outro_start=outro_start,
            silences=silences,
            scene_changes=analysis.get("scene_changes", []),
            energy_windows=analysis.get("energy_windows", []),
            segments=segments,
            clip_min_seconds=self._settings.clip_min_seconds,
            clip_max_seconds=self._settings.clip_max_seconds,
        )

        # Kanalin diger videolarindaki mevcut adaylarla benzerlik kontrolu.
        async with self._sessionmaker() as session:
            existing_rows = (
                (
                    await session.execute(
                        sa.select(ClipCandidate, Transcript)
                        .join(
                            SourceVideo,
                            ClipCandidate.source_video_id == SourceVideo.id,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id
                            == SourceChannel.id,
                        )
                        .join(
                            MediaAsset,
                            MediaAsset.source_video_id == SourceVideo.id,
                        )
                        .join(
                            Transcript,
                            Transcript.media_asset_id == MediaAsset.id,
                        )
                        .where(SourceChannel.channel_id == channel_id)
                        .where(SourceVideo.id != source_video_id)
                        .where(ClipCandidate.status == "candidate")
                    )
                )
                .all()
            )
            existing_texts = [
                (
                    candidate.id,
                    transcript_text_in_range(
                        t.segments,
                        candidate.start_seconds,
                        candidate.end_seconds,
                    ),
                )
                for candidate, t in existing_rows
            ]

        async with self._sessionmaker() as session:
            await session.execute(
                sa.delete(ClipCandidate).where(
                    ClipCandidate.source_video_id == source_video_id
                )
            )
            inserted = 0
            rejected = 0
            for spec in specs:
                text = transcript_text_in_range(
                    segments, spec.start_seconds, spec.end_seconds
                )
                duplicate_of = find_near_duplicate(text, existing_texts)
                status = "candidate"
                if duplicate_of is not None:
                    status = "rejected"
                    rejected += 1
                else:
                    inserted += 1
                session.add(
                    ClipCandidate(
                        source_video_id=source_video_id,
                        start_seconds=spec.start_seconds,
                        end_seconds=spec.end_seconds,
                        duration_seconds=spec.duration_seconds,
                        score=spec.score,
                        reason=spec.reason,
                        status=status,
                        duplicate_of_candidate_id=duplicate_of,
                        detail=spec.detail,
                    )
                )
            asset = await session.get(MediaAsset, asset_id)
            self._complete_stage(asset, "candidates")
            record_event(
                session,
                channel_id,
                "media.candidates",
                {
                    "source_video_id": source_video_id,
                    "candidates": inserted,
                    "rejected_duplicates": rejected,
                },
            )
            await session.commit()
