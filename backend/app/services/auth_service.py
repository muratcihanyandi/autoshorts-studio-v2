"""Studio login and session handling (product surface).

The studio is a single-operator product: the first visit creates the
operator password (hashed here, never stored raw), later visits require
a signed HttpOnly session cookie. Configuration lives in ``app_meta``
so no credential is ever committed or read from code.

The middleware is deliberately conservative:

- When no password is configured yet, the API stays open so the
  first-run setup screen can create it. This is also what keeps the
  test suite and local development usable.
- Once configured, every ``/api`` route except health/auth is closed
  without a valid cookie. Media streaming and thumbnails are protected
  by the same gate.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings

AUTH_META_KEY = "studio_auth"
SESSION_COOKIE = "autoshorts_session"
PBKDF2_ITERATIONS = 260_000
MIN_PASSWORD_CHARS = 8
MAX_USERNAME_CHARS = 64

# Auth uçları ve sağlık kontrolü giriş öncesi erişilebilir olmalı.
PUBLIC_API_PREFIXES = (
    "/api/health",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/logout",
)
# Ürün arayüzü bu belgeleri kullanmaz; oturum açmadan görünmesinler.
PROTECTED_DOC_PATHS = ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")


class AuthError(Exception):
    """Auth failure with a user-facing Turkish message and HTTP status."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a per-password random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}"
        f"${_b64encode(salt)}${_b64encode(digest)}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_session(config: dict[str, Any], username: str) -> str:
    """Compact signed token: base64(payload).base64(hmac)."""
    ttl = int(config.get("session_ttl_seconds") or 7 * 24 * 3600)
    payload = json.dumps(
        {"sub": username, "exp": int(time.time()) + ttl},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    secret = str(config.get("session_secret") or "").encode("utf-8")  # secret-scan-ok
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def verify_session(config: dict[str, Any], token: str | None) -> str | None:
    """Return the username for a valid, unexpired token; else None."""
    if not token or "." not in token:
        return None
    payload_text, signature_text = token.split(".", 1)
    try:
        payload = _b64decode(payload_text)
        signature = _b64decode(signature_text)
        secret = str(config.get("session_secret") or "").encode("utf-8")  # secret-scan-ok
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(payload.decode("utf-8"))
        if int(claims.get("exp") or 0) <= int(time.time()):
            return None
        username = claims.get("sub")
        if not isinstance(username, str) or username != config.get("username"):
            return None
        return username
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def authenticate(
    config: dict[str, Any] | None, username: str, password: str
) -> bool:
    if config is None:
        return False
    if not hmac.compare_digest(
        str(config.get("username") or ""), username.strip()
    ):
        return False
    return verify_password(password, str(config.get("password_hash") or ""))


class AuthService:
    """Read/write the single ``studio_auth`` row in ``app_meta``."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def get_config(self) -> dict[str, Any] | None:
        from app.models import AppMeta

        async with self._sessionmaker() as session:
            row = await session.get(AppMeta, AUTH_META_KEY)
        if row is None or not isinstance(row.value, dict):
            return None
        config = dict(row.value)
        if not config.get("password_hash") or not config.get("session_secret"):
            return None
        return config

    async def setup(self, username: str, password: str) -> dict[str, Any]:
        username = username.strip()
        if len(username) < 3 or len(username) > MAX_USERNAME_CHARS:
            raise AuthError("Kullanıcı adı 3-64 karakter olmalı.")
        if len(password) < MIN_PASSWORD_CHARS:
            raise AuthError(
                f"Şifre en az {MIN_PASSWORD_CHARS} karakter olmalı."
            )
        from app.models import AppMeta

        config = {
            "username": username,
            "password_hash": hash_password(password),
            "session_secret": secrets.token_urlsafe(48),
            "session_ttl_seconds": self._settings.auth_session_ttl_seconds,
            "created_at": int(time.time()),
        }
        async with self._sessionmaker() as session:
            row = await session.get(AppMeta, AUTH_META_KEY)
            if row is not None and isinstance(row.value, dict) and row.value.get(
                "password_hash"
            ):
                raise AuthError("Yönetici girişi zaten kurulmuş.", 409)
            if row is None:
                session.add(AppMeta(key=AUTH_META_KEY, value=config))
            else:
                row.value = config
            await session.commit()
        return config

    @staticmethod
    def token_for(config: dict[str, Any]) -> str:
        return issue_session(config, str(config["username"]))

    @staticmethod
    def username_from_request(
        request: Request, config: dict[str, Any] | None
    ) -> str | None:
        if config is None:
            return None
        return verify_session(config, request.cookies.get(SESSION_COOKIE))


def install_auth_middleware(app: Any, settings: Settings) -> None:
    """Close every non-public API route once a password exists."""

    @app.middleware("http")
    async def studio_auth(request: Request, call_next):
        path = request.url.path
        is_api = path.startswith("/api")
        is_doc = path in PROTECTED_DOC_PATHS or path.startswith("/docs/")
        if not (is_api or is_doc):
            return await call_next(request)
        if is_api and any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in PUBLIC_API_PREFIXES
        ):
            return await call_next(request)

        config = getattr(request.app.state, "auth_config", None)
        if config is None:
            # İlk kurulum öncesi (veya DB'siz geliştirme) API açıktır;
            # parola oluşturulduğu anda bu dal kapanır.
            return await call_next(request)

        username = verify_session(config, request.cookies.get(SESSION_COOKIE))
        if username is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Oturum gerekli."},
            )
        request.state.auth_user = username
        return await call_next(request)


def cookie_settings(settings: Settings) -> dict[str, Any]:
    return {
        "key": SESSION_COOKIE,
        "max_age": settings.auth_session_ttl_seconds,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.auth_cookie_secure,
        "path": "/",
    }
