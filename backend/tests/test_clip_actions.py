"""clip_actions: medya kütüphanesi toplu klip eylemleri (Görev 4).

Toplu herkese açma / gizliye alma / kaldırma. YouTube protokolü sadık
MockTransport üzerinde koşar (görünürlük state'i update gövdesinden
takip edilir); doğrulama sqlite'ta yapılır.
"""
from __future__ import annotations

import asyncio

import httpx
import sqlalchemy as sa

from tests.test_publishing import _env, _seed  # noqa: F401 - paylasilan tohum

from app.services.clip_actions import (
    ClipActionError,
    bulk_clip_action,
)

SESSION_URI = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc123"


def _privacy_tracking_handler():
    """videos.update gövdesindeki privacyStatus'i state'e alır;
    videos.list aynısını rapor eder (public VE private testleri için)."""
    state = {"privacy": "private"}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(
            "https://www.googleapis.com/upload/youtube/v3/videos"
        ):
            if request.method == "POST":
                return httpx.Response(
                    200, headers={"Location": SESSION_URI}
                )
            return httpx.Response(201, json={"id": "yt-vid-123"})
        if url.startswith("https://www.googleapis.com/youtube/v3/videos"):
            if request.method == "PUT":
                body = request.read()
                import json

                payload = json.loads(body.decode("utf-8"))
                state["privacy"] = payload.get("status", {}).get(
                    "privacyStatus", "public"
                )
                return httpx.Response(200, json={"id": "yt-vid-123"})
            if request.method == "DELETE":
                state["privacy"] = "gone"
                return httpx.Response(204)
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "yt-vid-123",
                            "status": {
                                "privacyStatus": state["privacy"],
                                "uploadStatus": "uploaded",
                            },
                        }
                    ]
                },
            )
        if url.startswith("https://oauth2.googleapis.com/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "refreshed-token",  # secret-scan-ok
                    "expires_in": 3600,
                },
            )
        return httpx.Response(404)

    return handler


class TestBulkVisibility:
    def test_bulk_public_flips_verified_private_row(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _db = _env(tmp_path)
            try:
                from app.services.publishing_service import PublishingService

                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(_privacy_tracking_handler())
                ) as http:
                    await service.publish_clip(candidate_id, http=http)
                    result = await bulk_clip_action(
                        sessionmaker,
                        settings,
                        [1],
                        "public",
                        http=http,
                    )
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result["ok"] == 1 and result["errors"] == 0
        assert result["results"][0]["status"] == "ok"

    def test_bulk_private_clears_public_stamps(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _db = _env(tmp_path)
            try:
                from app.models import PublishedVideo
                from app.services.publishing_service import (
                    PublishingService,
                )

                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(_privacy_tracking_handler())
                ) as http:
                    await service.publish_clip(candidate_id, http=http)
                    async with sessionmaker() as session:
                        row_id = (
                            (
                                await session.execute(
                                    sa.select(PublishedVideo.id).where(
                                        PublishedVideo.clip_candidate_id
                                        == candidate_id
                                    )
                                )
                            )
                            .scalars()
                            .one()
                        )
                    # Zamanli yayin adimiyla herkese ac ...
                    await service.make_public(row_id, http=http)
                    # ... sonra toplu gizliye al.
                    private_result = await bulk_clip_action(
                        sessionmaker, settings, [1], "private", http=http
                    )
                    async with sessionmaker() as session:
                        fresh = await session.get(PublishedVideo, row_id)
                        state = (
                            fresh.visibility,
                            fresh.public_at,
                            fresh.published_at,
                        )
                return private_result, state
            finally:
                await engine.dispose()

        private_result, state = asyncio.run(scenario())
        assert private_result["ok"] == 1
        assert state[0] == "private"
        # Gizliye alindiginda yayin damgalari temizlenir: klip
        # gunluk sayaclardan duser.
        assert state[1] is None and state[2] is None

    def test_bulk_visibility_skips_unuploaded_clip(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _db = _env(tmp_path)
            try:
                # Render var, yayin kaydi yok.
                await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    metadata_status="draft",
                )
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(_privacy_tracking_handler())
                ) as http:
                    result = await bulk_clip_action(
                        sessionmaker, settings, [1], "public", http=http
                    )
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result["ok"] == 0
        assert result["skipped"] == 1
        assert "yüklenmemiş" in result["results"][0]["note"]


class TestBulkDelete:
    def test_bulk_delete_removes_clips(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _db = _env(tmp_path)
            try:
                from app.services.publishing_service import PublishingService

                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(_privacy_tracking_handler())
                ) as http:
                    await service.publish_clip(candidate_id, http=http)
                    result = await bulk_clip_action(
                        sessionmaker, settings, [1], "delete", http=http
                    )
                    from app.models import RenderedClip

                    async with sessionmaker() as session:
                        render = (
                            (
                                await session.execute(
                                    sa.select(RenderedClip).where(
                                        RenderedClip.clip_candidate_id
                                        == candidate_id
                                    )
                                )
                            )
                            .scalars()
                            .one()
                        )
                        status = render.status
                return result, status
            finally:
                await engine.dispose()

        result, status = asyncio.run(scenario())
        assert result["ok"] == 1
        assert status == "removed"


class TestBulkValidation:
    def test_rejects_unknown_action_and_empty_list(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _db = _env(tmp_path)
            try:
                errors = []
                for action, ids in (("explode", [1]), ("delete", [])):
                    try:
                        await bulk_clip_action(
                            sessionmaker, settings, ids, action
                        )
                    except ClipActionError as exc:
                        errors.append(str(exc))
                return errors
            finally:
                await engine.dispose()

        errors = asyncio.run(scenario())
        assert len(errors) == 2
        assert "Eylem" in errors[0]
        assert "seçilmedi" in errors[1]
