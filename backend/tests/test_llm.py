"""LLM provider manager: masked keys, bounded fallback, request logs.

CRUD runs through the API (TestClient). Completion flows run the
service directly inside their own event loop with their own engine and
injected mock HTTP transports, so simulated provider failures (500,
429, timeout, network, malformed bodies) are verified without any
vendor account and without cross-loop engine sharing.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from app.schemas_llm import LlmProviderCreate
from app.services.llm_service import LlmProviderService
from tests.conftest import _make_app

PRIMARY_KEY = "llm-primary-key-abcd"
SECONDARY_KEY = "llm-secondary-efgh"


# --- API (CRUD) tarafı ---


def _make_llm_app(tmp_path) -> TestClient:
    app = _make_app(tmp_path, token_encryption_key=Fernet.generate_key().decode())
    client = TestClient(app)
    client.__enter__()
    return client


def _add_provider(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Ana Saglayici",
        "provider_type": "openai",
        "api_base": "https://api.llm-primary.test/v1",
        "model_id": "test-model",
        "api_key": PRIMARY_KEY,  # secret-scan-ok: synthetic test key
        "priority": 1,
        "max_retries": 0,
    }
    payload.update(overrides)
    response = client.post("/api/llm/providers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _sync_rows(db_path: str, sql: str):
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(sql)).all()
    finally:
        engine.dispose()


class TestCrud:
    def test_create_masks_api_key_and_stores_encrypted(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            body = _add_provider(client)
            assert body["api_key"] == {"configured": True, "hint": "abcd"}
            # Ham anahtar hiçbir yanıtta yok.
            assert PRIMARY_KEY not in json.dumps(body)

            enc = _sync_rows(
                client.app.state.test_db_path,
                "SELECT api_key_enc FROM llm_providers",
            )[0][0]
            assert enc is not None
            assert PRIMARY_KEY not in enc
        finally:
            client.__exit__(None, None, None)

    def test_fourth_provider_is_rejected(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            for i in range(3):
                _add_provider(client, name=f"P{i}", priority=i + 1)
            response = client.post(
                "/api/llm/providers",
                json={
                    "name": "P3",
                    "provider_type": "openai",
                    "api_base": "https://x.test/v1",
                    "model_id": "m",
                    "api_key": "key-dorduncu-0000",  # secret-scan-ok: synthetic test key
                },
            )
            assert response.status_code == 409
        finally:
            client.__exit__(None, None, None)

    def test_patch_keeps_key_untouched_and_updates_fields(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            provider = _add_provider(client)
            response = client.patch(
                f"/api/llm/providers/{provider['id']}",
                json={"model_id": "yeni-model", "enabled": False},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["model_id"] == "yeni-model"
            assert body["enabled"] is False
            assert body["api_key"] == {"configured": True, "hint": "abcd"}
        finally:
            client.__exit__(None, None, None)

    def test_creation_without_cipher_key_returns_503(self, tmp_path):
        from app.main import create_app

        db_file = tmp_path / "bare.db"
        sync_engine = sa.create_engine(f"sqlite:///{db_file}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        bare = TestClient(
            create_app(
                Settings(database_url=f"sqlite+aiosqlite:///{db_file}")
            )
        )
        with bare:
            response = bare.post(
                "/api/llm/providers",
                json={
                    "name": "Anahtarsiz",
                    "provider_type": "openai",
                    "api_base": "https://x.test/v1",
                    "model_id": "m",
                    "api_key": "key-anahtarsiz-9999",  # secret-scan-ok: synthetic test key
                },
            )
            assert response.status_code == 503

    def test_invalid_api_base_is_rejected(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            response = client.post(
                "/api/llm/providers",
                json={
                    "name": "Bozuk",
                    "provider_type": "openai",
                    "api_base": "not-a-url",
                    "model_id": "m",
                    "api_key": "key-bozuk-url-1234",  # secret-scan-ok: synthetic test key
                },
            )
            assert response.status_code == 400
        finally:
            client.__exit__(None, None, None)

    def test_api_base_with_endpoint_path_is_rejected(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            for bad_base in (
                "https://x.test/v1/chat/completions",
                "https://x.test/v1/messages",
                "https://x.test/v1/models/m:generateContent",
            ):
                response = client.post(
                    "/api/llm/providers",
                    json={
                        "name": "Yollu",
                        "provider_type": "openai",
                        "api_base": bad_base,
                        "model_id": "m",
                        "api_key": "key-yollu-0000",  # secret-scan-ok: synthetic test key
                    },
                )
                assert response.status_code == 400, bad_base
                assert "otomatik" in response.json()["detail"]
        finally:
            client.__exit__(None, None, None)

    def test_invalid_env_cipher_key_returns_503_not_500(self, tmp_path):
        from app.main import create_app

        db_file = tmp_path / "badkey.db"
        sync_engine = sa.create_engine(f"sqlite:///{db_file}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        badkey = TestClient(
            create_app(
                Settings(
                    database_url=f"sqlite+aiosqlite:///{db_file}",
                    token_encryption_key="bozuk-ortam-anahtari",
                )
            )
        )
        with badkey:
            response = badkey.post(
                "/api/llm/providers",
                json={
                    "name": "BozukAnahtar",
                    "provider_type": "openai",
                    "api_base": "https://x.test/v1",
                    "model_id": "m",
                    "api_key": "key-bozuk-anahtar-1",  # secret-scan-ok: synthetic test key
                },
            )
            assert response.status_code == 503
            assert "geçersiz" in response.json()["detail"]

    def test_duplicate_copies_row_with_same_key(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            provider = _add_provider(client)
            response = client.post(
                f"/api/llm/providers/{provider['id']}/duplicate"
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["name"] == "Ana Saglayici (kopya)"
            assert body["enabled"] is False
            assert body["priority"] == 2
            assert body["api_key"] == {"configured": True, "hint": "abcd"}
            assert body["api_base"] == provider["api_base"]
            assert body["model_id"] == provider["model_id"]

            # Aynı şifreli anahtar gövdesi kopyalanır; yeniden şifrelenmez.
            rows = _sync_rows(
                client.app.state.test_db_path,
                "SELECT api_key_enc FROM llm_providers "
                "ORDER BY id",
            )
            assert rows[0][0] == rows[1][0]

            # İkinci kopya benzersiz isim alır.
            second = client.post(
                f"/api/llm/providers/{provider['id']}/duplicate"
            )
            assert second.status_code == 201
            assert second.json()["name"] == "Ana Saglayici (kopya) 2"
        finally:
            client.__exit__(None, None, None)

    def test_duplicate_respects_limit_and_missing_id(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            for i in range(3):
                _add_provider(client, name=f"P{i}", priority=i + 1)
            full = client.post("/api/llm/providers/1/duplicate")
            assert full.status_code == 409

            missing = client.post("/api/llm/providers/999/duplicate")
            assert missing.status_code == 404
        finally:
            client.__exit__(None, None, None)

    def test_overview_counts_enabled_providers(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            _add_provider(client, name="P1", priority=1)
            _add_provider(client, name="P2", priority=2, enabled=False)
            body = client.get("/api/overview").json()
            assert body["llm_providers"]["configured"] == 1
        finally:
            client.__exit__(None, None, None)

    def test_test_endpoint_via_api_reports_category(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            provider = _add_provider(client)
            response = client.post(f"/api/llm/providers/{provider['id']}/test")
            # Gerçek dış ağ yok: hata kategorisi 200 ile döner.
            assert response.status_code == 200
            assert response.json()["status"] in {
                "network",
                "http_error",
                "timeout",
            }
        finally:
            client.__exit__(None, None, None)

    def test_logs_endpoint_lists_attempts(self, tmp_path):
        client = _make_llm_app(tmp_path)
        try:
            provider = _add_provider(client)
            client.post(f"/api/llm/providers/{provider['id']}/test")
            body = client.get("/api/llm/logs").json()
            assert body["total"] >= 1
            assert body["logs"][0]["provider_name"] == "Ana Saglayici"
        finally:
            client.__exit__(None, None, None)


# --- zincir (fallback) tarafı: kendi motoru + kendi loop'u ---


def _run_chain(tmp_path, providers: list[dict], handler, **complete_kwargs):
    """Sağlayıcıları kur, complete() çalıştır; (sonuç|istisna, db_yolu) döner."""

    async def scenario():
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{db_path}",
            token_encryption_key=token_key,
        )
        engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
        try:
            service = LlmProviderService(sessionmaker, settings)
            for payload in providers:
                await service.create_provider(LlmProviderCreate(**payload))
            try:
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    result = await service.complete(
                        "merhaba", http=http, **complete_kwargs
                    )
                return ("ok", result)
            except Exception as exc:  # noqa: BLE001 - test beklenen hatayı ayırt eder
                return ("error", exc)
        finally:
            await engine.dispose()

    db_path = tmp_path / "chain.db"
    token_key = Fernet.generate_key().decode()
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    outcome = asyncio.run(scenario())
    return outcome, str(db_path)


PRIMARY_PAYLOAD = {
    "name": "Ana",
    "provider_type": "openai",
    "api_base": "https://api.llm-primary.test/v1",
    "model_id": "m",
    "api_key": PRIMARY_KEY,  # secret-scan-ok: synthetic test key
    "priority": 1,
    "max_retries": 0,
}

SECONDARY_PAYLOAD = {
    "name": "Yedek",
    "provider_type": "openai",
    "api_base": "https://api.llm-secondary.test/v1",
    "model_id": "m",
    "api_key": SECONDARY_KEY,  # secret-scan-ok: synthetic test key
    "priority": 2,
    "max_retries": 0,
}


def _openai_body(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


class TestFallbackChain:
    def test_primary_failure_falls_back_to_secondary(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if "llm-primary" in str(request.url):
                return httpx.Response(500, json={"error": "down"})
            return httpx.Response(200, json=_openai_body("yedekten yanit"))

        (kind, result), db = _run_chain(
            tmp_path, [PRIMARY_PAYLOAD, SECONDARY_PAYLOAD], handler
        )
        assert kind == "ok"
        assert result.provider_name == "Yedek"
        assert result.text == "yedekten yanit"

        rows = _sync_rows(
            db,
            "SELECT request_id, provider_name, status FROM llm_request_logs "
            "ORDER BY id",
        )
        assert len(rows) == 2
        assert rows[0][1] == "Ana" and rows[0][2] == "http_error"
        assert rows[1][1] == "Yedek" and rows[1][2] == "success"
        assert rows[0][0] == rows[1][0]  # aynı istek grubu

    def test_null_content_is_invalid_response_not_crash(self, tmp_path):
        """Dusunen model token butcesini dusunmeye harcayip content null
        dondurunce zincir AttributeError ile degil, tanimli
        invalid_response ile kapanir (canli durum: gemma reasoning)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": None},
                            "finish_reason": "length",
                        }
                    ]
                },
            )

        (kind, exc), db = _run_chain(tmp_path, [PRIMARY_PAYLOAD], handler)
        assert kind == "error"
        from app.services.llm_service import LlmServiceError

        assert isinstance(exc, LlmServiceError)  # AttributeError degil
        rows = _sync_rows(
            db, "SELECT provider_name, status FROM llm_request_logs"
        )
        assert rows == [("Ana", "invalid_response")]

    def test_all_failures_raise_bounded_error(self, tmp_path):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500, json={"error": "down"})

        providers = [
            {**PRIMARY_PAYLOAD, "name": f"P{i}", "priority": i + 1}
            for i in range(3)
        ]
        (kind, exc), _ = _run_chain(tmp_path, providers, handler)
        assert kind == "error"
        # Sınırlı: 3 sağlayıcı x 1 deneme = 3 istek; sonsuz retry yok.
        assert calls["n"] == 3

    def test_rate_limit_category_and_fallback(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if "llm-primary" in str(request.url):
                return httpx.Response(429, json={"error": "rate"})
            return httpx.Response(200, json=_openai_body("yedek"))

        (kind, result), db = _run_chain(
            tmp_path, [PRIMARY_PAYLOAD, SECONDARY_PAYLOAD], handler
        )
        assert kind == "ok" and result.provider_name == "Yedek"

        status = _sync_rows(
            db,
            "SELECT status FROM llm_request_logs WHERE provider_name = 'Ana'",
        )[0][0]
        assert status == "rate_limited"

    def test_timeout_moves_to_next_provider(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if "llm-primary" in str(request.url):
                raise httpx.TimeoutException("sim")
            return httpx.Response(200, json=_openai_body("yedek"))

        (kind, result), db = _run_chain(
            tmp_path, [PRIMARY_PAYLOAD, SECONDARY_PAYLOAD], handler
        )
        assert kind == "ok" and result.provider_name == "Yedek"

        status = _sync_rows(
            db,
            "SELECT status FROM llm_request_logs WHERE provider_name = 'Ana'",
        )[0][0]
        assert status == "timeout"

    def test_network_error_retries_same_provider_then_moves_on(self, tmp_path):
        primary_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "llm-primary" in str(request.url):
                primary_calls["n"] += 1
                raise httpx.ConnectError("sim")
            return httpx.Response(200, json=_openai_body("yedek"))

        (kind, result), _ = _run_chain(
            tmp_path,
            [{**PRIMARY_PAYLOAD, "max_retries": 1}, SECONDARY_PAYLOAD],
            handler,
        )
        assert kind == "ok" and result.provider_name == "Yedek"
        # 1 + max_retries(1) = 2 deneme ana sağlayıcıya.
        assert primary_calls["n"] == 2

    def test_invalid_structured_response_falls_back(self, tmp_path):
        class Schema(BaseModel):
            cevap: str

        def handler(request: httpx.Request) -> httpx.Response:
            if "llm-primary" in str(request.url):
                return httpx.Response(200, json=_openai_body("bu json degil"))
            return httpx.Response(200, json=_openai_body('{"cevap": "tamam"}'))

        (kind, result), db = _run_chain(
            tmp_path,
            [PRIMARY_PAYLOAD, SECONDARY_PAYLOAD],
            handler,
            schema=Schema,
        )
        assert kind == "ok"
        assert result.provider_name == "Yedek"
        assert result.structured == {"cevap": "tamam"}

        status = _sync_rows(
            db,
            "SELECT status FROM llm_request_logs WHERE provider_name = 'Ana'",
        )[0][0]
        assert status == "invalid_response"

    def test_no_configured_provider_returns_error(self, tmp_path):
        (kind, exc), _ = _run_chain(tmp_path, [], lambda r: httpx.Response(200))
        assert kind == "error"
        assert "saglayici" in str(exc).lower() or "sağlayıcı" in str(exc)

    def test_anthropic_adapter_request_shape(self, tmp_path):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-api-key", "")
            return httpx.Response(
                200, json={"content": [{"type": "text", "text": "anthropic"}]}
            )

        payload = {
            **PRIMARY_PAYLOAD,
            "name": "AnthropicTip",
            "provider_type": "anthropic",
            "api_base": "https://api.anthropic-tip.test/v1",
        }
        (kind, result), _ = _run_chain(tmp_path, [payload], handler)
        assert kind == "ok" and result.text == "anthropic"
        assert seen["url"].endswith("/messages")
        assert seen["key"] == PRIMARY_KEY

    def test_google_adapter_request_shape(self, tmp_path):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "google"}]}}]},
            )

        payload = {
            **PRIMARY_PAYLOAD,
            "name": "GoogleTip",
            "provider_type": "google",
            "api_base": "https://api.google-tip.test/v1",
        }
        (kind, result), _ = _run_chain(tmp_path, [payload], handler)
        assert kind == "ok" and result.text == "google"
        assert ":generateContent" in seen["url"]
        assert f"key={PRIMARY_KEY}" in seen["url"]

    def test_success_result_via_test_provider(self, tmp_path):
        async def scenario():
            settings = Settings(
                database_url=f"sqlite+aiosqlite:///{db_path}",
                token_encryption_key=token_key,
            )
            engine, sessionmaker = create_engine_and_sessionmaker(
                settings.database_url
            )
            try:
                service = LlmProviderService(sessionmaker, settings)
                provider = await service.create_provider(
                    LlmProviderCreate(**PRIMARY_PAYLOAD)
                )
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda r: httpx.Response(200, json=_openai_body("pong"))
                    )
                ) as http:
                    return await service.test_provider(
                        provider.id, http=http
                    )
            finally:
                await engine.dispose()

        db_path = tmp_path / "ping.db"
        token_key = Fernet.generate_key().decode()
        sync_engine = sa.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        result = asyncio.run(scenario())
        assert result["status"] == "success"
        assert result["latency_ms"] >= 0
