"""Clip rendering pipeline (M8): candidate -> validated 9:16 clip.

One clip_render job renders one clip candidate. The webcam region
comes from calibration (manual region wins) or multi-frame detection;
uncertain detection routes the clip to 'review' instead of rendering a
wrong crop — nothing is rendered until the operator calibrates the
source or the threshold is met. Rendered rows are unique per candidate
so re-runs are idempotent.

M13: when the source's character carries a reference face, the
detected region is validated against it (character_match.similarity);
a low score falls back to a template search and, if that also fails,
the existing 'review' path. Sources without a character or reference
face behave exactly as before.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import cv2
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Character,
    ClipCandidate,
    MediaAsset,
    MediaInspection,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.channel_service import record_event
from app.services.character_match import search_region, similarity
from app.services.source_orientation import produces_full_cut
from app.services.vertical_render import (
    HORIZONTAL_H,
    HORIZONTAL_W,
    VerticalLayout,
    VerticalRenderError,
    build_layout,
    render_horizontal,
    render_vertical,
    validate_output,
)
from app.services.webcam_calibration import (
    ResolvedRegion,
    WebcamCalibrationService,
)
from app.services.webcam_detect import detect_webcam_region, sample_frames

# Karakter yuzu dogrulamasi icin varsayilan esik (kalibrasyondaki
# min_confidence bu esigi kaynak bazinda degistirebilir).
DEFAULT_CHARACTER_MATCH_THRESHOLD = 0.30


class VerticalPipelineError(Exception):
    """Pipeline failure with a user-facing Turkish message."""


def apply_character_validation(
    region: tuple[int, int, int, int],
    detection_confidence: float,
    frame_bgr,
    ref_bgr,
    threshold: float,
) -> tuple[tuple[int, int, int, int] | None, float, str | None]:
    """Validate a detected webcam region against the character's face.

    Returns (region, confidence, reason): the region passes when its
    similarity to the reference meets the threshold; otherwise a
    template search proposes a better window (rescue); a None region
    means the caller must route the clip to review.
    """
    frame_h, frame_w = frame_bgr.shape[:2]
    x, y, w, h = region
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame_w, x + w), min(frame_h, y + h)
    if x1 <= x0 or y1 <= y0:
        return None, 0.0, "webcam bolgesi kare icinde degil"
    crop = frame_bgr[y0:y1, x0:x1]
    score = similarity(crop, ref_bgr)
    if score >= threshold:
        return region, detection_confidence, None
    found = search_region(frame_bgr, ref_bgr)
    if found is not None and found[4] >= threshold:
        return (found[0], found[1], found[2], found[3]), found[4], None
    return None, score, (
        f"karakter yuzu eslesmesi yetersiz ({score:.2f} < {threshold:.2f})"
    )


class VerticalPipelineService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._calibrations = WebcamCalibrationService(sessionmaker)

    async def run(self, clip_candidate_id: int) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            candidate = await session.get(ClipCandidate, clip_candidate_id)
            if candidate is None:
                raise VerticalPipelineError("Klip adayi bulunamadi.")
            if candidate.status == "rejected":
                raise VerticalPipelineError(
                    "Reddedilmis aday render edilemez."
                )
            asset = (
                (
                    await session.execute(
                        sa.select(MediaAsset).where(
                            MediaAsset.source_video_id
                            == candidate.source_video_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if asset is None:
                raise VerticalPipelineError(
                    "Adayin medya dosyasi bulunamadi; once medya islemesi gerekir."
                )
            video = await session.get(SourceVideo, candidate.source_video_id)
            source = await session.get(
                SourceChannel, video.source_channel_id
            )
            channel_id = source.channel_id
            source_channel_id = source.id
            existing_render = (
                (
                    await session.execute(
                        sa.select(RenderedClip).where(
                            RenderedClip.clip_candidate_id == clip_candidate_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )

        if existing_render is not None and existing_render.status == "rendered":
            return {"clip_candidate_id": clip_candidate_id, "skipped": True}

        # Webcam bolgesi: kalibrasyon (manuel) > tespit.
        calibration = await self._calibrations.get(source_channel_id)
        if calibration is not None and calibration.manual:
            detection = None  # manuel bolge: tespit gerekmez
        else:
            # to_thread: tespit (ve AV1'de ffmpeg yedegi) donguyu bloklamaz.
            detection = await asyncio.to_thread(
                detect_webcam_region,
                asset.file_path,
                candidate.start_seconds,
                candidate.end_seconds,
                ffmpeg_bin=self._settings.ffmpeg_bin,
            )
        resolved = self._calibrations.resolve(calibration, detection)
        resolved = await self._validate_against_character(
            resolved,
            source,
            asset.file_path,
            candidate.start_seconds,
            candidate.end_seconds,
            calibration,
        )

        render_row = await self._ensure_render_row(clip_candidate_id)

        if resolved.region is None:
            confidence = detection.confidence if detection else 0.0
            await self._set_review(
                render_row.id,
                channel_id,
                clip_candidate_id,
                confidence,
                resolved.reason or "webcam bolgesi belirlenemedi",
            )
            return {
                "clip_candidate_id": clip_candidate_id,
                "review": True,
                "reason": resolved.reason,
            }

        async with self._sessionmaker() as session:
            inspection = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            source_w = inspection.width if inspection else 0
            source_h = inspection.height if inspection else 0

        try:
            layout = build_layout(source_w, source_h, resolved.region)
            out_path = (
                self._edited_dir() / f"{clip_candidate_id}.mp4"
            )
            expected = candidate.end_seconds - candidate.start_seconds
            await render_vertical(
                self._settings.ffmpeg_bin,
                asset.file_path,
                candidate.start_seconds,
                candidate.end_seconds,
                layout,
                out_path,
                threads=self._settings.ffmpeg_threads,
            )
            report = await validate_output(
                self._settings.ffprobe_bin, out_path, expected
            )
            if not report.ok:
                raise VerticalRenderError(
                    "Cikti dogrulamasi basarisiz: " + "; ".join(report.problems)
                )
        except VerticalRenderError as exc:
            await self._mark_failed(render_row.id, str(exc))
            raise VerticalPipelineError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - render hatasi kayda gecer
            message = f"{type(exc).__name__}: {exc}"
            await self._mark_failed(render_row.id, message)
            raise VerticalPipelineError(message) from exc

        async with self._sessionmaker() as session:
            row = await session.get(RenderedClip, render_row.id)
            row.status = "rendered"
            row.file_path = str(out_path)
            row.file_bytes = out_path.stat().st_size
            row.width = report.width
            row.height = report.height
            row.duration_seconds = report.duration_seconds
            row.layout = layout.as_dict()
            row.validation = {
                "ok": report.ok,
                "av_sync_delta": report.av_sync_delta,
                "has_audio": report.has_audio,
            }
            row.webcam_region = {
                "x": resolved.region[0],
                "y": resolved.region[1],
                "w": resolved.region[2],
                "h": resolved.region[3],
            }
            row.webcam_confidence = resolved.confidence
            if not row.thumbnail_path:
                preview = await self._write_preview_thumbnail(
                    render_row.id, out_path
                )
                if preview:
                    row.thumbnail_path = preview
            record_event(
                session,
                channel_id,
                "render.done",
                {
                    "clip_candidate_id": clip_candidate_id,
                    "file_bytes": row.file_bytes,
                    "webcam_confidence": resolved.confidence,
                    "manual_region": resolved.manual,
                },
            )
            await session.commit()
        return {"clip_candidate_id": clip_candidate_id, "rendered": True}

    async def run_full_cut(self, source_video_id: int) -> dict[str, Any]:
        """Reaksiyon kaynagi videonun yatay tam kesidi (M13).

        Tek satir RenderedClip: clip_candidate_id NULL, source_video_id
        dolu, orientation 'horizontal'. Kaynak reaksiyon degilse sert
        guvenlik reddeder; satir kaynak basina tektir (kod guvenligi).
        Dikey aday akisi bu yontemden etkilenmez.
        """
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None:
                raise VerticalPipelineError("Kaynak video bulunamadi.")
            source = await session.get(
                SourceChannel, video.source_channel_id
            )
            if source is None:
                raise VerticalPipelineError("Kaynak kanal bulunamadi.")
            if not produces_full_cut(source):
                # Hak kuralı: yatay tam kesit üretmeyen yön hiçbir koşulda
                # yatay satır üretmez (Görev 2: vertical yönü).
                raise VerticalPipelineError(
                    "Yatay tam kesit yalnızca yatay/reaksiyon kaynaklarında "
                    "üretilir."
                )
            channel_id = source.channel_id
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
                raise VerticalPipelineError(
                    "Videonun medya dosyasi bulunamadi; once medya "
                    "islemesi gerekir."
                )
            existing = (
                (
                    await session.execute(
                        sa.select(RenderedClip).where(
                            RenderedClip.source_video_id == source_video_id,
                            RenderedClip.orientation == "horizontal",
                            RenderedClip.clip_candidate_id.is_(None),
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            trim_start = max(0.0, float(source.trim_start_seconds or 0.0))
            trim_end = max(0.0, float(source.trim_end_seconds or 0.0))

        if existing is not None and existing.status == "rendered":
            return {"source_video_id": source_video_id, "skipped": True}

        render_row = await self._ensure_full_cut_row(source_video_id)

        async with self._sessionmaker() as session:
            inspection = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
        if inspection is None:
            message = "Videonun inspeksiyon kaydi yok; sure bilinmiyor."
            await self._mark_failed(render_row.id, message)
            raise VerticalPipelineError(message)
        duration = inspection.duration_seconds

        try:
            out_path = (
                self._edited_dir()
                / f"video_{source_video_id}_horizontal.mp4"
            )
            await render_horizontal(
                self._settings.ffmpeg_bin,
                asset.file_path,
                out_path,
                trim_start=trim_start,
                trim_end=trim_end,
                source_duration=duration,
                threads=self._settings.ffmpeg_threads,
            )
            report = await validate_output(
                self._settings.ffprobe_bin,
                out_path,
                duration - trim_start - trim_end,
                expected_size=(HORIZONTAL_W, HORIZONTAL_H),
            )
            if not report.ok:
                raise VerticalRenderError(
                    "Cikti dogrulamasi basarisiz: "
                    + "; ".join(report.problems)
                )
        except VerticalRenderError as exc:
            await self._mark_failed(render_row.id, str(exc))
            raise VerticalPipelineError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - render hatasi kayda gecer
            message = f"{type(exc).__name__}: {exc}"
            await self._mark_failed(render_row.id, message)
            raise VerticalPipelineError(message) from exc

        async with self._sessionmaker() as session:
            row = await session.get(RenderedClip, render_row.id)
            row.status = "rendered"
            row.file_path = str(out_path)
            row.file_bytes = out_path.stat().st_size
            row.width = report.width
            row.height = report.height
            row.duration_seconds = report.duration_seconds
            row.validation = {
                "ok": report.ok,
                "av_sync_delta": report.av_sync_delta,
                "has_audio": report.has_audio,
            }
            if not row.thumbnail_path:
                preview = await self._write_preview_thumbnail(
                    render_row.id, out_path
                )
                if preview:
                    row.thumbnail_path = preview
            record_event(
                session,
                channel_id,
                "render.done",
                {
                    "source_video_id": source_video_id,
                    "orientation": "horizontal",
                    "file_bytes": row.file_bytes,
                    "trim_start_seconds": trim_start,
                    "trim_end_seconds": trim_end,
                },
            )
            await session.commit()
        return {"source_video_id": source_video_id, "rendered": True}

    # --- yardimcilar ---

    async def _validate_against_character(
        self,
        resolved: ResolvedRegion,
        source: SourceChannel,
        video_path: str,
        start_seconds: float,
        end_seconds: float,
        calibration,
    ) -> ResolvedRegion:
        """Karakter yuzu dogrulamasi (M13). Karakter yok, referans yuz
        yok veya manuel kalibrasyon varsa cozum oldugu gibi doner."""
        if resolved.region is None or resolved.manual:
            return resolved
        if source.character_id is None:
            return resolved
        ref_bgr = await self._load_reference_face(source.character_id)
        if ref_bgr is None:
            return resolved
        frames = await asyncio.to_thread(
            sample_frames,
            video_path,
            start_seconds,
            end_seconds,
            ffmpeg_bin=self._settings.ffmpeg_bin,
        )
        if not frames:
            return resolved  # kare okunamadi: tespit sonucu gecerli sayilir
        frame = frames[0][1]
        threshold = (
            calibration.min_confidence
            if calibration is not None
            and calibration.min_confidence is not None
            else DEFAULT_CHARACTER_MATCH_THRESHOLD
        )
        region, confidence, reason = apply_character_validation(
            resolved.region, resolved.confidence, frame, ref_bgr, threshold
        )
        return ResolvedRegion(region, confidence, False, reason)

    async def _load_reference_face(self, character_id: int):
        """Karakterin referans yuzunu yukle; yoksa/okunamazsa None."""
        async with self._sessionmaker() as session:
            character = await session.get(Character, character_id)
        if character is None or not character.reference_face_path:
            return None
        if not self._settings.media_root:
            return None
        path = (
            Path(self._settings.media_root)
            / character.reference_face_path
        )
        image = cv2.imread(str(path))
        return image if image is not None else None

    async def _write_preview_thumbnail(
        self, render_id: int, video_path: Path
    ) -> str | None:
        """Kütüphane kartı için metinsiz önizleme kapağı (best-effort).

        Onay adımı gerçek metinli kapağı ayrı bir yola yazar; bu önizleme
        yalnızca hazır klip listesinde oynatıcı yerine görsel göstermek
        içindir ve üretilemezse akışı durdurmaz.
        """
        if not self._settings.media_root:
            return None
        from app.services.thumbnail import compose

        relative = f"thumbnails/preview_{render_id}.jpg"
        output = Path(self._settings.media_root) / relative
        try:
            await compose(
                self._settings.ffmpeg_bin, video_path, "", output
            )
        except Exception:  # noqa: BLE001 - önizleme isteğe bağlı
            return None
        return relative

    def _edited_dir(self):
        from pathlib import Path

        if not self._settings.media_root:
            raise VerticalPipelineError(
                "MEDIA_ROOT yapilandirilmamis; render hedefi yok."
            )
        return Path(self._settings.media_root) / "edited"

    async def _ensure_render_row(self, clip_candidate_id: int) -> RenderedClip:
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(RenderedClip).where(
                            RenderedClip.clip_candidate_id == clip_candidate_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                row = RenderedClip(clip_candidate_id=clip_candidate_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def _ensure_full_cut_row(
        self, source_video_id: int
    ) -> RenderedClip:
        """Yatay tam kesit satiri: kaynak basina tek (kod guvenligi)."""
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(RenderedClip).where(
                            RenderedClip.source_video_id == source_video_id,
                            RenderedClip.orientation == "horizontal",
                            RenderedClip.clip_candidate_id.is_(None),
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                row = RenderedClip(
                    clip_candidate_id=None,
                    source_video_id=source_video_id,
                    orientation="horizontal",
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def _set_review(
        self,
        render_id: int,
        channel_id: int,
        clip_candidate_id: int,
        confidence: float,
        reason: str,
    ) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RenderedClip, render_id)
            row.status = "review"
            row.webcam_confidence = confidence
            row.last_error = reason
            record_event(
                session,
                channel_id,
                "render.review",
                {
                    "clip_candidate_id": clip_candidate_id,
                    "confidence": confidence,
                    "reason": reason,
                },
            )
            await session.commit()

    async def _mark_failed(self, render_id: int, message: str) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RenderedClip, render_id)
            if row is None:
                return
            row.status = "failed"
            row.last_error = message[:2000]
            await session.commit()
