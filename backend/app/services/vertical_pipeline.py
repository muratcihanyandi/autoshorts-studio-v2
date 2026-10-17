"""Clip rendering pipeline (M8): candidate -> validated 9:16 clip.

One clip_render job renders one clip candidate. The webcam region
comes from calibration (manual region wins) or multi-frame detection;
uncertain detection routes the clip to 'review' instead of rendering a
wrong crop — nothing is rendered until the operator calibrates the
source or the threshold is met. Rendered rows are unique per candidate
so re-runs are idempotent.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    ClipCandidate,
    MediaAsset,
    MediaInspection,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.channel_service import record_event
from app.services.vertical_render import (
    VerticalLayout,
    VerticalRenderError,
    build_layout,
    render_vertical,
    validate_output,
)
from app.services.webcam_calibration import WebcamCalibrationService
from app.services.webcam_detect import detect_webcam_region


class VerticalPipelineError(Exception):
    """Pipeline failure with a user-facing Turkish message."""


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
            detection = detect_webcam_region(
                asset.file_path,
                candidate.start_seconds,
                candidate.end_seconds,
            )
        resolved = self._calibrations.resolve(calibration, detection)

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

    # --- yardimcilar ---

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
