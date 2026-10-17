"""LLM provider manager with bounded fallback (ADR-011).

Up to three configured providers form a chain. A completion request
walks enabled providers in priority order; each provider is attempted
`1 + max_retries` times (retries only for network/timeout errors), then
the chain moves on. Every attempt writes a status + latency row to
llm_request_logs, grouped by a request UUID. Once the chain is exhausted
the request fails outright — there is no background retry loop, so the
total number of attempts per request is bounded.

API keys are Fernet-encrypted at rest and only ever leave this layer as
a masked hint. Prompts, responses, and keys are never logged.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import LlmProvider, LlmRequestLog
from app.schemas_llm import (
    ApiKeyView,
    LlmProviderCreate,
    LlmProviderOut,
    LlmProviderUpdate,
    LlmTestResult,
)
from app.security import TokenCipher
from app.services.channel_service import record_event

PROVIDER_TYPES = ("openai", "anthropic", "google")
MAX_PROVIDERS = 3
HINT_MIN_LENGTH = 8

STATUS_SUCCESS = "success"
STATUS_TIMEOUT = "timeout"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_HTTP_ERROR = "http_error"
STATUS_NETWORK = "network"
STATUS_INVALID_RESPONSE = "invalid_response"
STATUS_NOT_CONFIGURED = "not_configured"

T = TypeVar("T", bound=BaseModel)


class LlmServiceError(Exception):
    """Provider management or completion failure (Turkish message)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LlmResult:
    text: str
    provider_name: str
    latency_ms: int
    structured: dict | list | None = None


def _default_http_client() -> httpx.AsyncClient:
    """Indirection point so tests can inject a mock transport."""
    return httpx.AsyncClient(timeout=15)


def _validate_api_base(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise LlmServiceError("api_base geçerli bir http(s) adresi olmalı.")
    return value.rstrip("/")


class LlmProviderService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    # --- CRUD ---

    def _cipher(self) -> TokenCipher:
        if not self._settings.token_encryption_key:
            raise LlmServiceError(
                "Token şifreleme anahtarı yapılandırılmamış; önce Ayarlar "
                "ekranından girin.",
                status_code=503,
            )
        return TokenCipher(self._settings.token_encryption_key)

    def _hint(self, provider: LlmProvider) -> str:
        try:
            key = self._cipher().decrypt(provider.api_key_enc)
        except Exception:  # noqa: BLE001 - ipucu best-effort, hata değil
            return ""
        return key[-4:] if len(key) >= HINT_MIN_LENGTH else ""

    def _out(self, provider: LlmProvider) -> LlmProviderOut:
        return LlmProviderOut(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            api_base=provider.api_base,
            model_id=provider.model_id,
            api_key=ApiKeyView(configured=True, hint=self._hint(provider)),
            enabled=provider.enabled,
            priority=provider.priority,
            timeout_seconds=provider.timeout_seconds,
            max_retries=provider.max_retries,
        )

    async def list_providers(self) -> list[LlmProviderOut]:
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmProvider).order_by(
                            LlmProvider.priority, LlmProvider.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [self._out(row) for row in rows]

    async def _get(self, session: AsyncSession, provider_id: int) -> LlmProvider:
        row = await session.get(LlmProvider, provider_id)
        if row is None:
            raise LlmServiceError("Sağlayıcı bulunamadı.", status_code=404)
        return row

    async def create_provider(self, data: LlmProviderCreate) -> LlmProviderOut:
        api_base = _validate_api_base(data.api_base)
        cipher = self._cipher()
        async with self._sessionmaker() as session:
            count = len(
                (
                    await session.execute(select(LlmProvider.id))
                ).scalars().all()
            )
            if count >= MAX_PROVIDERS:
                raise LlmServiceError(
                    f"En fazla {MAX_PROVIDERS} sağlayıcı desteklenir "
                    "(ana + iki yedek).",
                    status_code=409,
                )
            duplicate = (
                await session.execute(
                    select(LlmProvider).where(LlmProvider.name == data.name)
                )
            ).scalars().one_or_none()
            if duplicate is not None:
                raise LlmServiceError("Bu isimde bir sağlayıcı zaten var.", 409)
            row = LlmProvider(
                name=data.name,
                provider_type=data.provider_type.value,
                api_base=api_base,
                model_id=data.model_id,
                api_key_enc=cipher.encrypt(data.api_key),
                enabled=data.enabled,
                priority=data.priority,
                timeout_seconds=data.timeout_seconds,
                max_retries=data.max_retries,
            )
            session.add(row)
            record_event(session, None, "llm.provider_created", {"name": data.name})
            await session.commit()
            await session.refresh(row)
        return self._out(row)

    async def update_provider(
        self, provider_id: int, data: LlmProviderUpdate
    ) -> LlmProviderOut:
        patch = data.model_dump(exclude_unset=True)
        if "api_base" in patch and patch["api_base"] is not None:
            patch["api_base"] = _validate_api_base(patch["api_base"])
        async with self._sessionmaker() as session:
            row = await self._get(session, provider_id)
            if "name" in patch and patch["name"] != row.name:
                duplicate = (
                    await session.execute(
                        select(LlmProvider).where(LlmProvider.name == patch["name"])
                    )
                ).scalars().one_or_none()
                if duplicate is not None:
                    raise LlmServiceError(
                        "Bu isimde bir sağlayıcı zaten var.", 409
                    )
            api_key = patch.pop("api_key", None)
            if api_key:
                row.api_key_enc = self._cipher().encrypt(api_key)
            for field, value in patch.items():
                if value is not None:
                    setattr(row, field, value)
            record_event(session, None, "llm.provider_updated", {"name": row.name})
            await session.commit()
            await session.refresh(row)
        return self._out(row)

    async def delete_provider(self, provider_id: int) -> bool:
        async with self._sessionmaker() as session:
            row = await self._get(session, provider_id)
            record_event(session, None, "llm.provider_deleted", {"name": row.name})
            await session.delete(row)
            await session.commit()
        return True

    # --- completion with bounded fallback ---

    async def _load_chain(self) -> list[LlmProvider]:
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmProvider)
                        .where(LlmProvider.enabled.is_(True))
                        .order_by(LlmProvider.priority, LlmProvider.id)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows[:MAX_PROVIDERS])

    async def _log(
        self, request_id: str, provider: LlmProvider, status: str, latency_ms: int
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                LlmRequestLog(
                    request_id=request_id,
                    provider_id=provider.id,
                    provider_name=provider.name,
                    status=status,
                    latency_ms=latency_ms,
                )
            )
            await session.commit()

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int = 1024,
        http: httpx.AsyncClient | None = None,
    ) -> LlmResult:
        """Run the provider chain; validate JSON output against `schema`."""
        chain = await self._load_chain()
        if not chain:
            raise LlmServiceError(
                "Yapılandırılmış LLM sağlayıcısı yok.", status_code=503
            )
        request_id = str(uuid.uuid4())
        client = http or _default_http_client()
        owned = http is None
        try:
            for provider in chain:
                api_key = self._cipher().decrypt(provider.api_key_enc)
                attempts = 1 + provider.max_retries
                for attempt in range(attempts):
                    started = time.monotonic()
                    try:
                        text = await self._call(
                            client, provider, api_key, prompt, max_tokens
                        )
                        latency = int((time.monotonic() - started) * 1000)
                    except httpx.TimeoutException:
                        latency = int((time.monotonic() - started) * 1000)
                        await self._log(
                            request_id, provider, STATUS_TIMEOUT, latency
                        )
                        break  # zaman aşımı: sonraki sağlayıcı
                    except httpx.HTTPError:
                        latency = int((time.monotonic() - started) * 1000)
                        await self._log(
                            request_id, provider, STATUS_NETWORK, latency
                        )
                        if attempt < attempts - 1:
                            continue  # ağ hatası: bu sağlayıcıyı tekrar dene
                        break
                    except _ProviderHttpError as exc:
                        latency = int((time.monotonic() - started) * 1000)
                        status = (
                            STATUS_RATE_LIMITED
                            if exc.status_code == 429
                            else STATUS_HTTP_ERROR
                        )
                        await self._log(request_id, provider, status, latency)
                        break  # HTTP hatası: sonraki sağlayıcı
                    except _BadResponseBody:
                        latency = int((time.monotonic() - started) * 1000)
                        await self._log(
                            request_id,
                            provider,
                            STATUS_INVALID_RESPONSE,
                            latency,
                        )
                        break  # bozuk gövde: sonraki sağlayıcı

                    structured: dict | list | None = None
                    if schema is not None:
                        parsed = _parse_json(text)
                        if parsed is None or not _validates(parsed, schema):
                            await self._log(
                                request_id,
                                provider,
                                STATUS_INVALID_RESPONSE,
                                latency,
                            )
                            break  # geçersiz yanıt: sonraki sağlayıcı
                        structured = parsed

                    await self._log(request_id, provider, STATUS_SUCCESS, latency)
                    return LlmResult(
                        text=text,
                        provider_name=provider.name,
                        latency_ms=latency,
                        structured=structured,
                    )
        finally:
            if owned:
                await client.aclose()
        raise LlmServiceError(
            "Tüm LLM sağlayıcıları başarısız oldu; ayrıntılar günlüklerde.",
            status_code=502,
        )

    async def _call(
        self,
        client: httpx.AsyncClient,
        provider: LlmProvider,
        api_key: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        """One provider attempt; returns the response text."""
        if provider.provider_type == "openai":
            return await self._call_openai(
                client, provider, api_key, prompt, max_tokens
            )
        if provider.provider_type == "anthropic":
            return await self._call_anthropic(
                client, provider, api_key, prompt, max_tokens
            )
        return await self._call_google(
            client, provider, api_key, prompt, max_tokens
        )

    async def _call_openai(
        self,
        client: httpx.AsyncClient,
        provider: LlmProvider,
        api_key: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        response = await client.post(
            f"{provider.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": provider.model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            timeout=provider.timeout_seconds,
        )
        if response.status_code != 200:
            raise _ProviderHttpError(response.status_code)
        try:
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - bozuk gövde -> invalid
            raise _BadResponseBody from exc

    async def _call_anthropic(
        self,
        client: httpx.AsyncClient,
        provider: LlmProvider,
        api_key: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        response = await client.post(
            f"{provider.api_base}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": provider.model_id,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=provider.timeout_seconds,
        )
        if response.status_code != 200:
            raise _ProviderHttpError(response.status_code)
        try:
            return response.json()["content"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            raise _BadResponseBody from exc

    async def _call_google(
        self,
        client: httpx.AsyncClient,
        provider: LlmProvider,
        api_key: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        response = await client.post(
            f"{provider.api_base}/models/{provider.model_id}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
            timeout=provider.timeout_seconds,
        )
        if response.status_code != 200:
            raise _ProviderHttpError(response.status_code)
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            raise _BadResponseBody from exc

    async def test_provider(
        self, provider_id: int, http: httpx.AsyncClient | None = None
    ) -> dict:
        """One-shot connectivity check against a single provider."""
        async with self._sessionmaker() as session:
            provider = await self._get(session, provider_id)
        client = http or _default_http_client()
        owned = http is None
        started = time.monotonic()
        try:
            api_key = self._cipher().decrypt(provider.api_key_enc)
            text = await self._call(client, provider, api_key, "ping", 8)
            latency = int((time.monotonic() - started) * 1000)
            await self._log(
                str(uuid.uuid4()), provider, STATUS_SUCCESS, latency
            )
            result = LlmTestResult(
                provider_id=provider.id,
                status=STATUS_SUCCESS,
                latency_ms=latency,
                detail=text[:200],
            )
        except _ProviderHttpError as exc:
            latency = int((time.monotonic() - started) * 1000)
            status = (
                STATUS_RATE_LIMITED
                if exc.status_code == 429
                else STATUS_HTTP_ERROR
            )
            await self._log(str(uuid.uuid4()), provider, status, latency)
            result = LlmTestResult(
                provider_id=provider.id,
                status=status,
                latency_ms=latency,
                detail=f"HTTP {exc.status_code}",
            )
        except httpx.HTTPError as exc:
            latency = int((time.monotonic() - started) * 1000)
            status = (
                STATUS_TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else STATUS_NETWORK
            )
            await self._log(str(uuid.uuid4()), provider, status, latency)
            result = LlmTestResult(
                provider_id=provider.id,
                status=status,
                latency_ms=latency,
                detail=type(exc).__name__,
            )
        finally:
            if owned:
                await client.aclose()
        return result.model_dump()

    async def recent_logs(self, limit: int = 50) -> list[LlmRequestLog]:
        limit = max(1, min(limit, 200))
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmRequestLog)
                        .order_by(LlmRequestLog.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)


class _ProviderHttpError(Exception):
    """Non-200 provider response; status decides the log category."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _BadResponseBody(Exception):
    """200 with an unusable body; treated as an invalid response."""


def _parse_json(text: str) -> dict | list | None:
    import json

    stripped = text.strip()
    # Bazı sağlayıcılar JSON'u kod bloğuna sarar.
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _validates(parsed: dict | list, schema: type[T]) -> bool:
    try:
        schema.model_validate(parsed)
    except Exception:  # noqa: BLE001 - doğrulanamadı demesi yeterli
        return False
    return True
