"""vertical_pipeline: clip_render job end to end (M8).

Seeds a full chain (channel -> source -> video -> asset -> inspection
-> candidate) pointing at the real face-stream fixture, then runs the
clip_render job through the actual JobWorker. Covers the acceptance
criteria: rendered layout, uncertainty -> review, manual calibration,
idempotency, and the worker's candidate feed.

M13: reaction sources also render one horizontal full cut per video
(candidate NULL, code-guarded); character-bound sources validate the
webcam region against the reference face.
"""
from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    Character,
    ClipCandidate,
    MediaAsset,
    MediaInspection,
    RenderedClip,
    SourceChannel,
    SourceVideo,
    WebcamCalibration,
)
from tests.conftest import _make_app
from tests.media_sample import make_face_stream_video


def _vertical_env(tmp_path, **overrides):
    db_path = tmp_path / "vertical.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(media_root=str(tmp_path / "media"))
    kwargs.update(overrides)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **kwargs
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine


def _sync_rows(tmp_path, query: str):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/vertical.db")
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(query)).all()
    finally:
        engine.dispose()


async def _seed_chain(
    sessionmaker,
    media_path: str,
    *,
    reaction: bool = False,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    character_ref_path: str | None = None,
) -> tuple[int, int]:
    """Kanal -> kaynak -> video -> asset(+inspeksiyon) -> aday;
    (channel_id, candidate_id). M13 secenekleri: reaksiyon kaynagi,
    budama degerleri ve karakterin referans yuz yolu."""
    async with sessionmaker() as session:
        channel = Channel(name="Kanal")
        session.add(channel)
        await session.flush()
        from app.models import PublishingProfile

        # Start/Stop donemi: render isleri yalnizca calisan kanalda yurur.
        session.add(
            PublishingProfile(
                channel_id=channel.id, automation_state="running"
            )
        )
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCkaynak",
            title="Kaynak",
            permission_status="authorized",
            reaction_source=reaction,
            trim_start_seconds=trim_start,
            trim_end_seconds=trim_end,
        )
        session.add(source)
        await session.flush()
        if character_ref_path is not None:
            character = Character(
                name="Yayinci",
                reference_face_path=character_ref_path,
            )
            session.add(character)
            await session.flush()
            source.character_id = character.id
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="vid-1",
            title="Yuz videosu",
            status="processed",
        )
        session.add(video)
        await session.flush()
        asset = MediaAsset(
            source_video_id=video.id,
            origin="local_import",
            status="processed",
            stage="candidates",
            file_path=media_path,
            file_bytes=1000,
        )
        session.add(asset)
        await session.flush()
        session.add(
            MediaInspection(
                media_asset_id=asset.id,
                duration_seconds=8.0,
                width=1280,
                height=720,
                fps=15.0,
                video_codec="h264",
                has_audio=True,
            )
        )
        candidate = ClipCandidate(
            source_video_id=video.id,
            start_seconds=1.0,
            end_seconds=4.0,
            duration_seconds=3.0,
            score=0.8,
            # Start/Stop donemi: render beslemesi yalnizca hype secimi
            # ('selected') yapmis adaylari alir.
            status="selected",
        )
        session.add(candidate)
        await session.commit()
        return channel.id, candidate.id


@pytest.fixture(scope="module")
def face_video(tmp_path_factory):
    return make_face_stream_video(
        tmp_path_factory.mktemp("vpipeline") / "face_stream.mp4"
    )


class TestClipRenderPipeline:
    def test_worker_renders_candidate_end_to_end(self, tmp_path, face_video):
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                channel_id, candidate_id = await _seed_chain(
                    sessionmaker, str(face_video)
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "clip_render", {"clip_candidate_id": candidate_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id, candidate_id
            finally:
                await engine.dispose()

        job_id, candidate_id = asyncio.run(scenario())
        assert _sync_one_status(tmp_path, job_id) == "succeeded"
        rows = _sync_rows(
            tmp_path,
            "SELECT status, file_path, width, height, webcam_confidence"
            " FROM rendered_clips",
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "rendered"
        assert (row.width, row.height) == (1080, 1920)
        assert row.webcam_confidence >= 0.5  # tespit guveniyle render edildi
        # Dosya gercekten var ve medya agacindaki yerinde
        import os

        assert row.file_path and os.path.isfile(row.file_path)
        # Denetim izi
        events = {
            r.event_type
            for r in _sync_rows(tmp_path, "SELECT event_type FROM audit_events")
        }
        assert "render.done" in events

    def test_rerun_is_idempotent(self, tmp_path, face_video):
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(sessionmaker, str(face_video))
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                for _ in range(2):
                    job = await worker._jobs.enqueue(
                        "clip_render", {"clip_candidate_id": candidate_id}
                    )
                    await worker._jobs.claim_next(worker._worker_id)
                    await worker.run_job(job.id)
                return candidate_id
            finally:
                await engine.dispose()

        candidate_id = asyncio.run(scenario())
        rows = _sync_rows(tmp_path, "SELECT id FROM rendered_clips")
        assert len(rows) == 1  # ikinci kosma yeni satir acmaz

    def test_uncertain_detection_routes_to_review(self, tmp_path, face_video):
        """Kabul kriteri: webcam belirsizligi incelemeye dusurur."""
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(sessionmaker, str(face_video))
                # Esigi imkansiz yap: tespit guveni asla yetmez
                async with sessionmaker() as session:
                    source_id = (
                        await session.execute(
                            sa.select(SourceChannel.id).limit(1)
                        )
                    ).scalar_one()
                    session.add(
                        WebcamCalibration(
                            source_channel_id=source_id,
                            region_x=0,
                            region_y=0,
                            region_w=10,
                            region_h=10,
                            manual=False,
                            min_confidence=0.999,
                        )
                    )
                    await session.commit()
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "clip_render", {"clip_candidate_id": candidate_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = asyncio.run(scenario())
        assert _sync_one_status(tmp_path, job_id) == "succeeded"  # is hata degil
        rows = _sync_rows(
            tmp_path, "SELECT status, last_error FROM rendered_clips"
        )
        assert rows[0].status == "review"
        assert rows[0].last_error is not None
        events = {
            r.event_type
            for r in _sync_rows(tmp_path, "SELECT event_type FROM audit_events")
        }
        assert "render.review" in events
        # Render edilen dosya yok
        renders = _sync_rows(
            tmp_path, "SELECT file_path FROM rendered_clips"
        )
        assert renders[0].file_path == ""

    def test_manual_calibration_overrides_detection(self, tmp_path, face_video):
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(sessionmaker, str(face_video))
                async with sessionmaker() as session:
                    source_id = (
                        await session.execute(
                            sa.select(SourceChannel.id).limit(1)
                        )
                    ).scalar_one()
                    session.add(
                        WebcamCalibration(
                            source_channel_id=source_id,
                            region_x=250,
                            region_y=130,
                            region_w=110,
                            region_h=110,
                            manual=True,
                        )
                    )
                    await session.commit()
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "clip_render", {"clip_candidate_id": candidate_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return candidate_id
            finally:
                await engine.dispose()

        asyncio.run(scenario())
        rows = _sync_rows(
            tmp_path, "SELECT status, webcam_region FROM rendered_clips"
        )
        assert rows[0].status == "rendered"
        # Manuel bolge oldugu gibi kullanildi
        import json

        region = json.loads(rows[0].webcam_region)
        assert (region["x"], region["y"], region["w"], region["h"]) == (
            250,
            130,
            110,
            110,
        )

    def test_rejected_candidate_refused(self, tmp_path, face_video):
        from app.services.vertical_pipeline import (
            VerticalPipelineError,
            VerticalPipelineService,
        )

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(sessionmaker, str(face_video))
                async with sessionmaker() as session:
                    await session.execute(
                        sa.update(ClipCandidate)
                        .where(ClipCandidate.id == candidate_id)
                        .values(status="rejected")
                    )
                    await session.commit()
                service = VerticalPipelineService(sessionmaker, settings)
                try:
                    await service.run(candidate_id)
                    return None
                except VerticalPipelineError as exc:
                    return str(exc)
            finally:
                await engine.dispose()

        message = asyncio.run(scenario())
        assert message is not None


def _sync_one_status(tmp_path, job_id: int) -> str:
    engine = sa.create_engine(f"sqlite:///{tmp_path}/vertical.db")
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job_id}
            ).scalar()
    finally:
        engine.dispose()


class TestWorkerRenderFeed:
    def test_enqueue_render_jobs_skips_already_rendered(self, tmp_path, face_video):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(sessionmaker, str(face_video))
                # Ikinci aday: zaten render satiri var
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                    second = ClipCandidate(
                        source_video_id=video_id,
                        start_seconds=4.0,
                        end_seconds=6.0,
                        duration_seconds=2.0,
                        score=0.5,
                        status="candidate",
                    )
                    session.add(second)
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=second.id,
                            status="rendered",
                            file_path="/done.mp4",
                        )
                    )
                    await session.commit()

                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_render_jobs()
                added_again = await worker.enqueue_render_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, j.payload) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = asyncio.run(scenario())
        # Sadece render edilmemis aday kuyruga girer; tekrar dedupe.
        assert added == 1
        assert added_again == 0
        assert jobs[0][0] == "clip_render"
        assert jobs[0][1]["clip_candidate_id"] == 1


class TestCalibrationApi:
    def test_put_get_delete_roundtrip(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            channel = client.post(
                "/api/channels", json={"name": "Kanal"}
            ).json()
            source = client.post(
                f"/api/channels/{channel['id']}/sources",
                json={
                    "youtube_channel_id": "UCtest",
                    "title": "Kaynak",
                    "rights_record": {
                        "granted_by": "Sahibi",
                        "evidence_url": "https://ornek.test/hak",
                    },
                },
            ).json()
            source_id = source["id"]

            missing = client.get(f"/api/sources/{source_id}/webcam-calibration")
            assert missing.status_code == 404

            created = client.put(
                f"/api/sources/{source_id}/webcam-calibration",
                json={
                    "region": {"x": 10, "y": 20, "w": 200, "h": 150},
                    "manual": True,
                },
            )
            assert created.status_code == 200, created.text
            assert created.json()["region_w"] == 200

            # Gecersiz bolge reddedilir
            invalid = client.put(
                f"/api/sources/{source_id}/webcam-calibration",
                json={"region": {"x": -5, "y": 0, "w": 100, "h": 100}},
            )
            assert invalid.status_code == 400

            deleted = client.delete(
                f"/api/sources/{source_id}/webcam-calibration"
            )
            assert deleted.status_code == 204
            gone = client.get(f"/api/sources/{source_id}/webcam-calibration")
            assert gone.status_code == 404


def _write_reference_face(media_root, name: str, image) -> str:
    """Referans yuz dosyasini medya agacina yaz; goreli yol doner."""
    import cv2
    from pathlib import Path

    ref_dir = Path(media_root) / "characters"
    ref_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"characters/{name}"
    assert cv2.imwrite(str(Path(media_root) / rel_path), image)
    return rel_path


def _pd_reference_image():
    import cv2

    from app.services.character_match import extract_reference

    photo = cv2.imread(
        str(__import__("pathlib").Path(__file__).parent / "assets" / "face_pd.jpg")
    )
    reference = extract_reference(photo)
    assert reference is not None
    return reference


def _noise_reference_image():
    import numpy as np

    rng = np.random.default_rng(3)
    return rng.integers(0, 256, size=(200, 200, 3), dtype=np.uint8)


class TestFullCutPipeline:
    """M13: reaksiyon kaynaginin yatay tam kesidi."""

    def test_full_cut_renders_with_trims(self, tmp_path, face_video):
        from app.services.vertical_pipeline import VerticalPipelineService

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                await _seed_chain(
                    sessionmaker,
                    str(face_video),
                    reaction=True,
                    trim_start=1.0,
                    trim_end=2.0,
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = VerticalPipelineService(sessionmaker, settings)
                result = await service.run_full_cut(video_id)
                return result, video_id
            finally:
                await engine.dispose()

        result, video_id = asyncio.run(scenario())
        assert result == {"source_video_id": video_id, "rendered": True}
        rows = _sync_rows(
            tmp_path,
            "SELECT orientation, clip_candidate_id, source_video_id,"
            " status, width, height, file_path FROM rendered_clips",
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.orientation == "horizontal"
        assert row.clip_candidate_id is None  # tam kesit: aday YOK
        assert row.source_video_id == video_id
        assert row.status == "rendered"
        assert (row.width, row.height) == (1920, 1080)
        import os

        assert row.file_path and os.path.isfile(row.file_path)
        events = {
            r.event_type
            for r in _sync_rows(tmp_path, "SELECT event_type FROM audit_events")
        }
        assert "render.done" in events

    def test_full_cut_idempotent(self, tmp_path, face_video):
        from app.services.vertical_pipeline import VerticalPipelineService

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                await _seed_chain(
                    sessionmaker, str(face_video), reaction=True
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = VerticalPipelineService(sessionmaker, settings)
                first = await service.run_full_cut(video_id)
                second = await service.run_full_cut(video_id)
                return first, second
            finally:
                await engine.dispose()

        first, second = asyncio.run(scenario())
        assert first.get("rendered") is True
        assert second.get("skipped") is True
        rows = _sync_rows(
            tmp_path,
            "SELECT id FROM rendered_clips WHERE orientation = 'horizontal'",
        )
        assert len(rows) == 1  # kaynak basina tek yatay satir

    def test_full_cut_refused_for_non_reaction_source(self, tmp_path, face_video):
        """Sert guvenlik: reaksiyon olmayan kaynak yatay satir uretmez."""
        from app.services.vertical_pipeline import (
            VerticalPipelineError,
            VerticalPipelineService,
        )

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                await _seed_chain(sessionmaker, str(face_video))
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = VerticalPipelineService(sessionmaker, settings)
                try:
                    await service.run_full_cut(video_id)
                    return None
                except VerticalPipelineError as exc:
                    return str(exc)
            finally:
                await engine.dispose()

        message = asyncio.run(scenario())
        assert message is not None and "reaksiyon" in message
        rows = _sync_rows(
            tmp_path,
            "SELECT COUNT(*) AS n FROM rendered_clips"
            " WHERE orientation = 'horizontal'",
        )
        assert rows[0].n == 0

    def test_candidate_render_never_creates_horizontal_row(
        self, tmp_path, face_video
    ):
        """Kabul kriteri: reaksiyon OLMAYAN kaynagin normal aday akisi
        hicbir kosulda yatay satir acmaz."""
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(
                    sessionmaker, str(face_video)
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "clip_render", {"clip_candidate_id": candidate_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = asyncio.run(scenario())
        assert _sync_one_status(tmp_path, job_id) == "succeeded"
        rows = _sync_rows(
            tmp_path,
            "SELECT orientation, COUNT(*) AS n FROM rendered_clips"
            " GROUP BY orientation",
        )
        assert len(rows) == 1
        assert rows[0].orientation == "vertical"

    def test_render_feed_includes_full_cut_jobs(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                # Reaksiyon kaynagi: aday + tam kesit isleri
                await _seed_chain(
                    sessionmaker, "/x.mp4", reaction=True
                )
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_render_jobs()
                added_again = await worker.enqueue_render_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, dict(j.payload)) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = asyncio.run(scenario())
        assert added == 2  # clip_render + clip_render_full_cut
        assert added_again == 0
        kinds = sorted(j[0] for j in jobs)
        assert kinds == ["clip_render", "clip_render_full_cut"]
        payloads = {j[0]: j[1] for j in jobs}
        assert "clip_candidate_id" in payloads["clip_render"]
        assert "source_video_id" in payloads["clip_render_full_cut"]

    def test_render_feed_skips_full_cut_for_plain_sources(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                await _seed_chain(sessionmaker, "/x.mp4")
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_render_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, [j.job_type for j in jobs]
            finally:
                await engine.dispose()

        added, kinds = asyncio.run(scenario())
        assert added == 1
        assert kinds == ["clip_render"]  # yalnizca dikey aday isi

    def test_worker_runs_full_cut_job_end_to_end(self, tmp_path, face_video):
        from app.services.media_storage import ensure_media_tree
        from app.worker import JobWorker, build_handlers

        ensure_media_tree(tmp_path / "media")

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                await _seed_chain(
                    sessionmaker, str(face_video), reaction=True
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "clip_render_full_cut", {"source_video_id": video_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id, video_id
            finally:
                await engine.dispose()

        job_id, video_id = asyncio.run(scenario())
        assert _sync_one_status(tmp_path, job_id) == "succeeded"
        rows = _sync_rows(
            tmp_path,
            "SELECT status, orientation, source_video_id"
            " FROM rendered_clips",
        )
        assert len(rows) == 1
        assert rows[0].status == "rendered"
        assert rows[0].orientation == "horizontal"
        assert rows[0].source_video_id == video_id


class TestCharacterValidationPipeline:
    """M13: karakter referans yuzuyle webcam dogrulamasi (uctan uca)."""

    def test_matching_reference_renders(self, tmp_path, face_video):
        from app.services.vertical_pipeline import VerticalPipelineService

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                # Karakter fotografi = karedeki yuz (PD fixture)
                ref_path = _write_reference_face(
                    settings.media_root, "1_ref.png", _pd_reference_image()
                )
                _, candidate_id = await _seed_chain(
                    sessionmaker, str(face_video), character_ref_path=ref_path
                )
                service = VerticalPipelineService(sessionmaker, settings)
                return await service.run(candidate_id)
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result.get("rendered") is True

    def test_mismatched_reference_routes_to_review(self, tmp_path, face_video):
        """Kabul kriteri: referans yuz eslesmezse mevcut review yolu."""
        from app.services.vertical_pipeline import VerticalPipelineService

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                ref_path = _write_reference_face(
                    settings.media_root, "2_ref.png", _noise_reference_image()
                )
                _, candidate_id = await _seed_chain(
                    sessionmaker, str(face_video), character_ref_path=ref_path
                )
                service = VerticalPipelineService(sessionmaker, settings)
                return await service.run(candidate_id)
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result.get("review") is True
        assert "karakter" in (result.get("reason") or "")
        rows = _sync_rows(
            tmp_path, "SELECT status, last_error FROM rendered_clips"
        )
        assert rows[0].status == "review"
        assert rows[0].last_error is not None

    def test_no_reference_face_behavior_unchanged(self, tmp_path, face_video):
        """Karakter yok: davranis bugunki haliyle ayni (render)."""
        from app.services.vertical_pipeline import VerticalPipelineService

        async def scenario():
            sessionmaker, settings, engine = _vertical_env(tmp_path)
            try:
                _, candidate_id = await _seed_chain(
                    sessionmaker, str(face_video)
                )
                service = VerticalPipelineService(sessionmaker, settings)
                return await service.run(candidate_id)
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result.get("rendered") is True


def test_missing_source_file_marks_render_failed_stops_feed(tmp_path):
    """Dosyası silinmiş aday (elle silinmiş indirme): render satırı
    'failed' işaretlenir ve besleme bu adayı tekrar seçmez — canlıda
    gece boyunca 170 işlik sonsuz yeniden deneme döngüsünün kökü
    buydu (satırsız hata beslemeyi yeniden tetikliyordu)."""
    from app.services.vertical_pipeline import VerticalPipelineService
    from app.worker import JobWorker

    async def scenario():
        sessionmaker, settings, engine = _vertical_env(tmp_path)
        try:
            _, candidate_id = await _seed_chain(
                sessionmaker, str(tmp_path / "media" / "downloads" / "yok.mp4")
            )
            service = VerticalPipelineService(sessionmaker, settings)
            error = None
            try:
                await service.run(candidate_id)
            except Exception as exc:  # noqa: BLE001 - hata tasiyici
                error = str(exc)
            worker = JobWorker(sessionmaker, settings)
            enqueued = await worker.enqueue_render_jobs()
            async with sessionmaker() as session:
                row = (
                    (
                        await session.execute(
                            sa.select(RenderedClip).where(
                                RenderedClip.clip_candidate_id == candidate_id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
            return error, row.status if row is not None else None, enqueued
        finally:
            await engine.dispose()

    error, render_status, enqueued = asyncio.run(scenario())
    assert error is not None  # hata kullaniciya tasinir
    assert render_status == "failed"  # satir kayitli
    assert enqueued == 0  # besleme yeniden is acmaz
