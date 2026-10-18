"""metadata_service: validation, templates, revisions, generation.

Generation runs against a MockTransport LLM (OpenAI shape); template
isolation, revision append semantics, and rejection of invalid output
are verified on sqlite.

M13: the system-prompt chain (character -> global -> built-in
default), hook/thumbnail_text persistence + length validation, and
the horizontal full-cut revision chain.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    Character,
    ClipCandidate,
    ClipMetadata,
    MediaAsset,
    MetadataTemplate,
    RenderedClip,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.schemas_llm import LlmProviderCreate
from app.services.llm_service import LlmProviderService
from app.services.metadata_service import (
    DEFAULT_SYSTEM_PROMPT,
    MetadataError,
    MetadataService,
    apply_pattern,
    dedupe_tags,
    validate_metadata,
)
from tests.conftest import _make_app

PROPOSAL = {
    "title": "Cok Onemli Bir Kesit",
    "summary": "Bu kesitte konusan kisi cok onemli bir konuyu anlatiyor"
    " ve herkesin izlemesi gereken bilgiler veriyor.",
    "tags": ["kesit", "turkce", "onemli"],
}

FULL_PROPOSAL = {
    **PROPOSAL,
    "hook": "Ilk 3 saniyede her sey degisiyor",
    "thumbnail_text": "BU KESITE BAK",
}

CHARACTER_PROMPT = (
    "Sen bu kanalin yayincisinin ses tonunu kullanan bir metaveri "
    "yazarisin."
)
GLOBAL_PROMPT = "Genel studo promptu: sade ve net ol."


def _openai_body(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _env(tmp_path):
    db_path = tmp_path / "m9meta.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


async def _add_provider(sessionmaker, settings):
    service = LlmProviderService(sessionmaker, settings)
    await service.create_provider(
        LlmProviderCreate(
            name="Test Saglayici",
            provider_type="openai",
            api_base="https://api.llm-test.test/v1",
            model_id="test-model",
            api_key="synthetic-test-key",  # secret-scan-ok: synthetic
            priority=1,
            max_retries=0,
        )
    )


async def _seed(
    sessionmaker, *, channel_name="Kanal", character_prompt=None
) -> tuple[int, int]:
    """Kanal -> kaynak -> video -> asset(+transkript) -> aday(+render);
    (channel_id, candidate_id)."""
    async with sessionmaker() as session:
        channel = Channel(name=channel_name)
        session.add(channel)
        await session.flush()
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCkaynak",
            title="Kaynak",
            permission_status="authorized",
        )
        session.add(source)
        await session.flush()
        if character_prompt is not None:
            character = Character(
                name="Yayinci", system_prompt=character_prompt
            )
            session.add(character)
            await session.flush()
            source.character_id = character.id
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="vid-1",
            title="Kaynak Video Basligi",
            status="processed",
        )
        session.add(video)
        await session.flush()
        asset = MediaAsset(
            source_video_id=video.id,
            origin="local_import",
            status="processed",
            stage="candidates",
            file_path="/x.mp4",
        )
        session.add(asset)
        await session.flush()
        session.add(
            Transcript(
                media_asset_id=asset.id,
                source="sidecar",
                segment_count=1,
                segments=[
                    {
                        "start": 1.0,
                        "end": 3.5,
                        "text": "bu kesitte onemli bir konu anlatiliyor",
                    }
                ],
            )
        )
        candidate = ClipCandidate(
            source_video_id=video.id,
            start_seconds=1.0,
            end_seconds=3.5,
            duration_seconds=2.5,
            score=0.8,
            status="candidate",
        )
        session.add(candidate)
        await session.flush()
        session.add(
            RenderedClip(
                clip_candidate_id=candidate.id,
                status="rendered",
                file_path="/edited/1.mp4",
            )
        )
        await session.commit()
        return channel.id, candidate.id


def _run(coro):
    return asyncio.run(coro)


async def _seed_full_cut(
    sessionmaker, *, reaction: bool = True, character_prompt: str | None = None
) -> tuple[int, int]:
    """Reaksiyon kaynagi + video + asset(+transkript) + yatay tam kesit
    render satiri; (channel_id, source_video_id)."""
    async with sessionmaker() as session:
        channel = Channel(name="Kanal")
        session.add(channel)
        await session.flush()
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCkaynak",
            title="Kaynak",
            permission_status="authorized",
            reaction_source=reaction,
        )
        session.add(source)
        await session.flush()
        if character_prompt is not None:
            character = Character(
                name="Yayinci", system_prompt=character_prompt
            )
            session.add(character)
            await session.flush()
            source.character_id = character.id
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="vid-1",
            title="Reaksiyon Videosu",
            status="processed",
        )
        session.add(video)
        await session.flush()
        asset = MediaAsset(
            source_video_id=video.id,
            origin="local_import",
            status="processed",
            stage="candidates",
            file_path="/x.mp4",
        )
        session.add(asset)
        await session.flush()
        session.add(
            Transcript(
                media_asset_id=asset.id,
                source="sidecar",
                segment_count=1,
                segments=[
                    {
                        "start": 0.0,
                        "end": 8.0,
                        "text": "tum reaksiyon videosunun transkripti burada",
                    }
                ],
            )
        )
        session.add(
            RenderedClip(
                clip_candidate_id=None,
                source_video_id=video.id,
                orientation="horizontal",
                status="rendered",
                file_path="/edited/video_1_horizontal.mp4",
            )
        )
        await session.commit()
        return channel.id, video.id


class TestPureLogic:
    def test_validate_metadata_rules(self):
        assert validate_metadata("Gecerli bir baslik", "En az yirmi karakter aciklama.", ["a"]) == []
        problems = validate_metadata("kisa", "En az yirmi karakter aciklama.", [])
        assert any("baslik" in p for p in problems)
        problems = validate_metadata(
            "Gecerli bir baslik", "kisa", []
        )
        assert any("aciklama" in p for p in problems)
        problems = validate_metadata(
            "Gecerli bir baslik",
            "En az yirmi karakter aciklama.",
            ["x" * 60],
        )
        assert problems

    def test_apply_pattern(self):
        values = {"title": "Baslik", "channel": "Kanal"}
        assert apply_pattern("{title} | {channel}", values) == "Baslik | Kanal"
        assert apply_pattern("{title} {bilinmeyen}", values) == "Baslik {bilinmeyen}"
        assert apply_pattern("sabit metin", values) == "sabit metin"

    def test_dedupe_tags(self):
        assert dedupe_tags(["A", "a", "b ", "", "c"]) == ["A", "b", "c"]


class TestGeneration:
    def test_generate_applies_template_and_stores_revision(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                channel_id, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )
                await service.set_template(
                    channel_id,
                    title_pattern="{title} | {channel}",
                    base_tags=["studyo"],
                )

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(PROPOSAL))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    result = await service.generate(candidate_id, http=http)
                return result, candidate_id
            finally:
                await engine.dispose()

        result, candidate_id = _run(scenario())
        assert result["revision"] == 1
        assert result["tags"] == 4  # 3 oneri + 1 sablon etiketi

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT title, description, tags, status FROM clip_metadata"
                )
            ).one()
            events = conn.execute(
                sa.text("SELECT event_type FROM audit_events")
            ).scalars().all()
        engine.dispose()
        assert row[0] == "Cok Onemli Bir Kesit | Kanal"  # sablon uygulandi
        assert row[1].startswith("Bu kesitte")
        assert json.loads(row[2]) == ["studyo", "kesit", "turkce", "onemli"]
        assert row[3] == "draft"
        assert "metadata.generated" in events

    def test_regenerate_appends_revision(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(PROPOSAL))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    first = await service.generate(candidate_id, http=http)
                    skipped = await service.generate(candidate_id, http=http)
                    second = await service.generate(
                        candidate_id, regenerate=True, http=http
                    )
                return first, skipped, second
            finally:
                await engine.dispose()

        first, skipped, second = _run(scenario())
        assert first["revision"] == 1
        assert skipped.get("skipped") is True  # varsayilan: yeniden uretmez
        assert second["revision"] == 2

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            revisions = conn.execute(
                sa.text(
                    "SELECT revision FROM clip_metadata"
                    " WHERE clip_candidate_id = 1 ORDER BY revision"
                )
            ).scalars().all()
        engine.dispose()
        assert revisions == [1, 2]  # revizyonlar eklenir, ezilmez

    def test_invalid_result_rejected(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                channel_id, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )
                # Gecerli bir oneri + basinca sablonu sisiren desen:
                # nihai baslik limiti asar, validate_metadata reddetmeli.
                await service.set_template(
                    channel_id,
                    title_pattern="{title} - {title} - {title} - {title} - {title} - {title}",
                )

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(PROPOSAL))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    try:
                        await service.generate(candidate_id, http=http)
                        error = None
                    except MetadataError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "baslik" in error
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM clip_metadata")
            ).scalar()
        engine.dispose()
        assert count == 0  # gecersiz metaveri kaydedilmez

    def test_template_isolation_between_channels(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                channel_a, candidate_a = await _seed(sessionmaker)
                channel_b, candidate_b = await _seed(
                    sessionmaker, channel_name="Diger Kanal"
                )
                service = MetadataService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )
                await service.set_template(
                    channel_a, title_pattern="A: {title}"
                )
                await service.set_template(
                    channel_b, title_pattern="B: {title}"
                )

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(PROPOSAL))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    await service.generate(candidate_a, http=http)
                    await service.generate(candidate_b, http=http)
                return candidate_a, candidate_b
            finally:
                await engine.dispose()

        candidate_a, candidate_b = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            title_a = conn.execute(
                sa.text(
                    f"SELECT title FROM clip_metadata"
                    f" WHERE clip_candidate_id = {candidate_a}"
                )
            ).scalar()
            title_b = conn.execute(
                sa.text(
                    f"SELECT title FROM clip_metadata"
                    f" WHERE clip_candidate_id = {candidate_b}"
                )
            ).scalar()
        engine.dispose()
        assert title_a.startswith("A: ")  # sablon degisikligi komsuyu etkilemez
        assert title_b.startswith("B: ")

    def test_worker_feed_enqueues_metadata_jobs(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(sessionmaker)
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_content_jobs()
                added_again = await worker.enqueue_content_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, j.payload) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = _run(scenario())
        assert added == 2  # altyazi duzeltme + metaveri
        assert added_again == 0
        types = sorted(j[0] for j in jobs)
        assert types == ["metadata_generate", "subtitle_correct"]


class TestTemplateApi:
    def test_template_roundtrip_and_validation(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            channel = client.post(
                "/api/channels", json={"name": "Kanal"}
            ).json()

            default = client.get(
                f"/api/channels/{channel['id']}/metadata-template"
            )
            assert default.status_code == 200, default.text
            assert default.json()["title_pattern"] == "{title}"

            updated = client.put(
                f"/api/channels/{channel['id']}/metadata-template",
                json={
                    "title_pattern": "{title} | {channel}",
                    "base_tags": ["shorts"],
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["base_tags"] == ["shorts"]

            # {title} icermeyen sablon reddedilir
            invalid = client.put(
                f"/api/channels/{channel['id']}/metadata-template",
                json={"title_pattern": "sabit baslik"},
            )
            assert invalid.status_code == 400

            missing = client.get("/api/channels/999/metadata-template")
            assert missing.status_code == 404


class TestPromptChain:
    """M13: sistem promptu zinciri karakter -> genel -> yerlesik."""

    def _capturing_handler(self, captured, payload):
        async def handler(request):
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json=_openai_body(payload))

        return handler

    def test_character_prompt_reaches_transport(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(
                    sessionmaker, character_prompt=CHARACTER_PROMPT
                )
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )
                captured: dict = {}

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        self._capturing_handler(captured, PROPOSAL)
                    )
                ) as http:
                    await service.generate(candidate_id, http=http)
                return captured
            finally:
                await engine.dispose()

        captured = _run(scenario())
        messages = captured["body"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == CHARACTER_PROMPT
        assert messages[1]["role"] == "user"

    def test_global_prompt_fallback(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(metadata_system_prompt=GLOBAL_PROMPT),
                )
                captured: dict = {}

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        self._capturing_handler(captured, PROPOSAL)
                    )
                ) as http:
                    await service.generate(candidate_id, http=http)
                return captured
            finally:
                await engine.dispose()

        captured = _run(scenario())
        messages = captured["body"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == GLOBAL_PROMPT

    def test_default_prompt_fallback(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(sessionmaker)
                # Karakter yok, genel prompt bos -> yerlesik varsayilan
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )
                captured: dict = {}

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        self._capturing_handler(captured, PROPOSAL)
                    )
                ) as http:
                    await service.generate(candidate_id, http=http)
                return captured
            finally:
                await engine.dispose()

        captured = _run(scenario())
        messages = captured["body"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == DEFAULT_SYSTEM_PROMPT

    def test_character_prompt_wins_over_global(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(
                    sessionmaker, character_prompt=CHARACTER_PROMPT
                )
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(metadata_system_prompt=GLOBAL_PROMPT),
                )
                captured: dict = {}

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        self._capturing_handler(captured, PROPOSAL)
                    )
                ) as http:
                    await service.generate(candidate_id, http=http)
                return captured
            finally:
                await engine.dispose()

        captured = _run(scenario())
        assert (
            captured["body"]["messages"][0]["content"] == CHARACTER_PROMPT
        )


class TestHookAndThumbnailText:
    def test_hook_and_thumbnail_text_persisted(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )

                async def handler(request):
                    return httpx.Response(
                        200, json=_openai_body(FULL_PROPOSAL)
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    await service.generate(candidate_id, http=http)
            finally:
                await engine.dispose()

        _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT hook, thumbnail_text FROM clip_metadata")
            ).one()
        engine.dispose()
        assert row[0] == FULL_PROPOSAL["hook"]
        assert row[1] == FULL_PROPOSAL["thumbnail_text"]

    def test_validate_metadata_hook_lengths(self):
        problems = validate_metadata(
            "Gecerli bir baslik",
            "En az yirmi karakter aciklama.",
            [],
            hook="x" * 121,
            thumbnail_text="y" * 81,
        )
        assert any("hook" in p for p in problems)
        assert any("thumbnail_text" in p for p in problems)
        assert (
            validate_metadata(
                "Gecerli bir baslik",
                "En az yirmi karakter aciklama.",
                [],
                hook="x" * 120,
                thumbnail_text="y" * 80,
            )
            == []
        )

    def test_overlong_hook_rejected_nothing_persisted(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, candidate_id = await _seed(sessionmaker)
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )
                overlong = {
                    **FULL_PROPOSAL,
                    "hook": "c" * 130,  # limit 120
                }

                async def handler(request):
                    return httpx.Response(
                        200, json=_openai_body(overlong)
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    try:
                        await service.generate(candidate_id, http=http)
                        error = None
                    except MetadataError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM clip_metadata")
            ).scalar()
        engine.dispose()
        assert count == 0


class TestFullCutMetadata:
    def test_generate_full_cut_stores_revision(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, video_id = await _seed_full_cut(sessionmaker)
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )

                async def handler(request):
                    return httpx.Response(
                        200, json=_openai_body(FULL_PROPOSAL)
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    first = await service.generate_full_cut(
                        video_id, http=http
                    )
                    skipped = await service.generate_full_cut(
                        video_id, http=http
                    )
                    second = await service.generate_full_cut(
                        video_id, regenerate=True, http=http
                    )
                return first, skipped, second, video_id
            finally:
                await engine.dispose()

        first, skipped, second, video_id = _run(scenario())
        assert first["revision"] == 1
        assert skipped.get("skipped") is True
        assert second["revision"] == 2

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9meta.db")
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT clip_candidate_id, source_video_id, revision,"
                    " hook, thumbnail_text FROM clip_metadata"
                    " ORDER BY revision"
                )
            ).all()
        engine.dispose()
        assert len(rows) == 2  # kaynak basina tek zincir, revizyonlar eklenir
        for row in rows:
            assert row[0] is None  # tam kesit: aday NULL
            assert row[1] == video_id
        assert rows[0][3] == FULL_PROPOSAL["hook"]
        assert rows[0][4] == FULL_PROPOSAL["thumbnail_text"]

    def test_generate_full_cut_refused_for_plain_source(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, video_id = await _seed_full_cut(
                    sessionmaker, reaction=False
                )
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(),
                )
                try:
                    await service.generate_full_cut(video_id)
                    return None
                except MetadataError as exc:
                    return str(exc)
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "reaksiyon" in error

    def test_full_cut_uses_character_prompt(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, video_id = await _seed_full_cut(
                    sessionmaker, character_prompt=CHARACTER_PROMPT
                )
                service = MetadataService(
                    sessionmaker,
                    LlmProviderService(sessionmaker, settings),
                    settings=Settings(metadata_system_prompt=GLOBAL_PROMPT),
                )
                captured: dict = {}

                async def handler(request):
                    captured["body"] = json.loads(request.read())
                    return httpx.Response(
                        200, json=_openai_body(FULL_PROPOSAL)
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    await service.generate_full_cut(video_id, http=http)
                return captured
            finally:
                await engine.dispose()

        captured = _run(scenario())
        messages = captured["body"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == CHARACTER_PROMPT
        # Tam transkript user prompta gider (pencere degil)
        assert "tum reaksiyon videosunun" in messages[1]["content"]

    def test_worker_feed_enqueues_full_cut_metadata(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _seed_full_cut(sessionmaker)
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_content_jobs()
                added_again = await worker.enqueue_content_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, dict(j.payload)) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = _run(scenario())
        # Tam kesit render + transkript var: altyazi duzeltme (asset) +
        # tam kesit metaverisi (source_video_id ile).
        payloads = [p for kind, p in jobs if kind == "metadata_generate"]
        assert payloads == [{"source_video_id": 1}]
        assert added >= 1
        assert added_again == 0
