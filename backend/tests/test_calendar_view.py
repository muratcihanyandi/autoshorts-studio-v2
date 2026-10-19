"""Görev 1: takvim görünümü — slot simülasyonu ve yayın geçmişi.

Kabul senaryoları: çalışan kanalın yayın dilimleri ay bazında listelenir;
gizli yüklenmiş video (verified + private) ilk uygun dilime kesin düşer
(scheduled), stoktaki hazır klip bir sonraki güne planlanır (planned),
günlük limit dolunca dilim boş kalır (empty) ve gerçekleşen yayın ay
içinde görünür (published). Kayıtlar tıklanabilir detay taşır: klip
render kimliği, metaveri özeti ve YouTube bağlantısı.

Simülasyon bugünden başladığı için sorgulanan ayın sonunda en az birkaç
gün kalmalı; ayın sonuna yaklaşılmışsa test bir sonraki ayı sorgular.
"""
from __future__ import annotations

import asyncio
from calendar import monthrange
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ClipCandidate,
    ClipMetadata,
    PublishedVideo,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.calendar_view import CalendarViewService
from tests.conftest import _make_app

PUBLISH_TIMES = ["09:00", "14:00", "20:00"]


def _run(coro):
    return asyncio.run(coro)


def _simulation_month(now: datetime) -> tuple[int, int]:
    """Simülasyonun rahat çalışması için sonuna en az 4 gün kalan ay."""
    if monthrange(now.year, now.month)[1] - now.day >= 4:
        return now.year, now.month
    if now.month == 12:
        return now.year + 1, 1
    return now.year, now.month + 1


def _public_moment(year: int, month: int, now: datetime) -> datetime:
    """Gerçekleşen yayın anı: geçerli ay sorgulanıyorsa şimdi, sonraki
    ay sorgulanıyorsa ayın 1'i (servis public_at'ı yalnız aya göre
    listeler, gelecek tarihli de dahil)."""
    if (year, month) == (now.year, now.month):
        return now
    return datetime(year, month, 1, 10, 0, tzinfo=UTC)


async def _seed(sessionmaker, *, public_moment: datetime) -> None:
    """Kanal (running, 3 dilim), yetkili kaynak ve üç dikey klip: yayına
    verilmiş (public), gizli yüklenmiş (verified + private) ve stokta
    bekleyen (render + taslak metaveri). Günlük dikey limit 1."""
    async with sessionmaker() as session:
        channel = Channel(name="Takvim Kanalı", status="connected")
        session.add(channel)
        await session.flush()
        session.add(
            PublishingProfile(
                channel_id=channel.id,
                automation_state="running",
                daily_clip_target=1,
                daily_horizontal_limit=0,
                settings={"publish_times": PUBLISH_TIMES},
            )
        )
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UC-cal",
            title="Kaynak",
            permission_status="authorized",
        )
        session.add(source)
        await session.flush()

        async def add_clip(key: str, *, score: float, meta_status: str):
            video = SourceVideo(
                source_channel_id=source.id,
                youtube_video_id=f"vid-{key}",
                title=f"Kaynak video {key}",
                status="processed",
            )
            session.add(video)
            await session.flush()
            candidate = ClipCandidate(
                source_video_id=video.id,
                start_seconds=0.0,
                end_seconds=30.0,
                duration_seconds=30.0,
                score=score,
                status="selected",
            )
            session.add(candidate)
            await session.flush()
            session.add(
                RenderedClip(
                    clip_candidate_id=candidate.id,
                    source_video_id=video.id,
                    orientation="vertical",
                    status="rendered",
                    file_path=f"/x/{key}.mp4",
                    file_bytes=10,
                )
            )
            session.add(
                ClipMetadata(
                    clip_candidate_id=candidate.id,
                    revision=1,
                    title=f"Klip {key}",
                    description="Takvim testi açıklaması.",
                    tags=[key],
                    status=meta_status,
                )
            )
            return candidate, video

        # 1) Yayina verilmis (public) klip: ay listesinde gorunur.
        pub_candidate, pub_video = await add_clip(
            "pub", score=0.95, meta_status="approved"
        )
        session.add(
            PublishedVideo(
                clip_candidate_id=pub_candidate.id,
                source_video_id=pub_video.id,
                orientation="vertical",
                channel_id=channel.id,
                youtube_video_id="yt-pub",
                visibility="public",
                status="verified",
                title="Klip pub",
                public_at=public_moment,
                published_at=public_moment,
            )
        )

        # 2) Gizli yuklenmis (scheduled) klip: siradaki dilime kesin duser.
        sch_candidate, sch_video = await add_clip(
            "sch", score=0.9, meta_status="approved"
        )
        session.add(
            PublishedVideo(
                clip_candidate_id=sch_candidate.id,
                source_video_id=sch_video.id,
                orientation="vertical",
                channel_id=channel.id,
                youtube_video_id="yt-sch",
                visibility="private",
                status="verified",
                title="Klip sch",
            )
        )

        # 3) Stoktaki (planned) klip: yuklenmemis, onay sonrasi duser.
        await add_clip("sto", score=0.8, meta_status="draft")

        await session.commit()


def test_calendar_slots_metadata_and_limits(tmp_path):
    async def scenario():
        db_path = tmp_path / "cal.db"
        sync_engine = sa.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")
        engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
        try:
            now = datetime.now(UTC)
            year, month = _simulation_month(now)
            await _seed(
                sessionmaker, public_moment=_public_moment(year, month, now)
            )
            service = CalendarViewService(sessionmaker, settings)
            return await service.calendar(year, month), now
        finally:
            await engine.dispose()

    data, now = _run(scenario())

    assert data["channels"][0]["publish_times"] == PUBLISH_TIMES
    assert data["channels"][0]["daily_vertical_limit"] == 1

    published = [e for e in data["entries"] if e["status"] == "published"]
    assert len(published) == 1
    assert published[0]["title"] == "Klip pub"
    assert published[0]["youtube_url"] == "https://www.youtube.com/watch?v=yt-pub"
    assert published[0]["metadata"]["tags"] == ["pub"]

    scheduled = [e for e in data["entries"] if e["status"] == "scheduled"]
    assert len(scheduled) == 1
    assert scheduled[0]["title"] == "Klip sch"
    assert scheduled[0]["metadata"]["status"] == "approved"
    assert scheduled[0]["clip_render_id"] is not None
    # Simulasyon yalnizca gelecek dilimlere yazar.
    assert scheduled[0]["scheduled_at"] > now.isoformat()

    planned = [e for e in data["entries"] if e["status"] == "planned"]
    assert len(planned) == 1
    assert planned[0]["title"] == "Klip sto"
    assert planned[0]["metadata"]["tags"] == ["sto"]

    # Gunluk dikey limit 1: stoktaki klip ayni dilime dukulemez, bir
    # sonraki gune dusmelidir.
    assert planned[0]["scheduled_at"] > scheduled[0]["scheduled_at"]

    # Kalan dilimler bos notu tasir (limit dolu ya da stok tukendi).
    empty = [e for e in data["entries"] if e["status"] == "empty"]
    assert len(empty) >= 1
    assert all(
        e["note"] in ("Günlük limit doldu", "Bu dilim için hazır video yok")
        for e in empty
    )


def test_calendar_api_roundtrip(tmp_path):
    app = _make_app(tmp_path)
    now = datetime.now(UTC)
    year, month = _simulation_month(now)

    async def seed_app_db():
        engine, sessionmaker = create_engine_and_sessionmaker(
            f"sqlite+aiosqlite:///{app.state.test_db_path}"
        )
        try:
            await _seed(
                sessionmaker, public_moment=_public_moment(year, month, now)
            )
        finally:
            await engine.dispose()

    _run(seed_app_db())

    with TestClient(app) as client:
        response = client.get(
            "/api/calendar", params={"year": year, "month": month}
        )
        assert response.status_code == 200, response.text
        payload = response.json()

    assert payload["month_label"]
    statuses = {entry["status"] for entry in payload["entries"]}
    assert {"published", "scheduled", "planned", "empty"} <= statuses
    channels = payload["channels"]
    assert channels[0]["name"] == "Takvim Kanalı"
    assert channels[0]["daily_vertical_limit"] == 1
    assert channels[0]["publish_times"] == PUBLISH_TIMES
