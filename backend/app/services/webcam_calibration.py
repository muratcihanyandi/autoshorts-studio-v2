"""Webcam calibration per source channel (M8).

A manual region is an operator decision and wins outright — detection
is skipped for that source. A confidence override tightens or loosens
the review threshold for one streamer without touching the global
default. Calibration changes affect only their own source channel.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import WebcamCalibration

DEFAULT_MIN_CONFIDENCE = 0.5


class CalibrationError(Exception):
    """Calibration failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ResolvedRegion:
    region: tuple[int, int, int, int] | None
    confidence: float
    manual: bool
    reason: str | None = None


class WebcamCalibrationService:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, source_channel_id: int) -> WebcamCalibration | None:
        async with self._sessionmaker() as session:
            return (
                (
                    await session.execute(
                        sa.select(WebcamCalibration).where(
                            WebcamCalibration.source_channel_id
                            == source_channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )

    async def set_calibration(
        self,
        source_channel_id: int,
        region: tuple[int, int, int, int],
        *,
        manual: bool = True,
        min_confidence: float | None = None,
    ) -> WebcamCalibration:
        """Create or replace the calibration for one source channel."""
        x, y, w, h = region
        if min(x, y) < 0 or w <= 0 or h <= 0:
            raise CalibrationError(
                "Bolge koordinatlari gecersiz: x,y >= 0 ve w,h > 0 gerekli."
            )
        if min_confidence is not None and not 0.0 <= min_confidence <= 1.0:
            raise CalibrationError(
                "min_confidence 0 ile 1 arasinda olmali."
            )
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(WebcamCalibration).where(
                            WebcamCalibration.source_channel_id
                            == source_channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                row = WebcamCalibration(source_channel_id=source_channel_id)
                session.add(row)
            row.region_x, row.region_y = int(x), int(y)
            row.region_w, row.region_h = int(w), int(h)
            row.manual = manual
            row.min_confidence = min_confidence
            await session.commit()
            await session.refresh(row)
            return row

    async def delete(self, source_channel_id: int) -> bool:
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(WebcamCalibration).where(
                            WebcamCalibration.source_channel_id
                            == source_channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    def resolve(
        self,
        calibration: WebcamCalibration | None,
        detection_result,
    ) -> ResolvedRegion:
        """Manual region wins; otherwise detection must beat the
        effective threshold, else the caller routes to review.
        detection_result=None (tespit atlandi) yalnizca manuel
        kalibrasyonla anlamlidir."""
        if calibration is not None and calibration.manual:
            return ResolvedRegion(
                region=(
                    calibration.region_x,
                    calibration.region_y,
                    calibration.region_w,
                    calibration.region_h,
                ),
                confidence=1.0,
                manual=True,
            )
        if detection_result is None:
            return ResolvedRegion(None, 0.0, False, "tespit yapilmadi")
        threshold = (
            calibration.min_confidence
            if calibration is not None and calibration.min_confidence is not None
            else DEFAULT_MIN_CONFIDENCE
        )
        if detection_result.region is None:
            return ResolvedRegion(
                None, detection_result.confidence, False, detection_result.reason
            )
        if detection_result.confidence < threshold:
            # Esik alti bolge guvenilmez: None doner, cagiran review'a
            # yonlendirir (yanlis kirpma render etmemek icin).
            return ResolvedRegion(
                None,
                detection_result.confidence,
                False,
                f"güven eşiğin altında ({detection_result.confidence:.2f}"
                f" < {threshold:.2f})",
            )
        return ResolvedRegion(
            detection_result.region, detection_result.confidence, False, None
        )
