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
from datetime import UTC, datetime
from typing import Any, NamedTuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
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
    "/api/auth/signup",
    "/api/auth/login",
    "/api/auth/logout",
)
# Ürün arayüzü bu belgeleri kullanmaz; oturum açmadan görünmesinler.
PROTECTED_DOC_PATHS = ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")

# --- Hesap sistemi (madde 6): plan kataloğu ve kapılar ---------------------
# Örnek abonelik: free tek kanal + temel otomasyon; pro her şeyi açar.
# Admin rolü plandan bağımsız olarak tüm kapıları geçer.
GATED_FEATURES = ("channels", "youtube_analytics", "bulk_actions", "manual_schedule")
FEATURE_LABELS = {
    "channels": "Ek kanal ekleme",
    "youtube_analytics": "YouTube analitiği",
    "bulk_actions": "Toplu işlemler",
    "manual_schedule": "Manuel yayın planlama",
}
PLAN_CATALOG: list[dict[str, Any]] = [
    {
        "id": "free",
        "name": "Ücretsiz",
        "price_note": "0",
        "max_channels": 1,
        "features": [
            {"key": "automation", "label": "Otomatik üretim ve yayın", "included": True},
            {"key": "youtube_analytics", "label": "YouTube analitiği", "included": False},
            {"key": "bulk_actions", "label": "Toplu işlemler", "included": False},
            {"key": "manual_schedule", "label": "Manuel yayın planlama", "included": False},
        ],
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_note": "199",
        "max_channels": None,
        "features": [
            {"key": "automation", "label": "Otomatik üretim ve yayın", "included": True},
            {"key": "youtube_analytics", "label": "YouTube analitiği", "included": True},
            {"key": "bulk_actions", "label": "Toplu işlemler", "included": True},
            {"key": "manual_schedule", "label": "Manuel yayın planlama", "included": True},
        ],
    },
]
FREE_MAX_CHANNELS = 1


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
    stored_username = str(config.get("username") or "").encode("utf-8")
    provided_username = username.strip().encode("utf-8")
    if not hmac.compare_digest(stored_username, provided_username):
        return False
    return verify_password(password, str(config.get("password_hash") or ""))


# --- Çok kullanıcılı oturum (madde 6) --------------------------------------


class SessionUser(NamedTuple):
    """Oturum açan hesabın kimliği; middleware her istekte state'e koyar."""

    id: int
    username: str
    role: str
    plan: str
    plan_expires_at: str | None
    is_active: bool
    token_version: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def effective_plan(self) -> str:
        """Süresi geçmiş Pro, free sayılır."""
        if self.plan != "pro":
            return self.plan
        if self.plan_expires_at:
            try:
                expires = datetime.fromisoformat(self.plan_expires_at)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires <= datetime.now(UTC):
                    return "free"
            except ValueError:
                return "free"
        return "pro"


def _session_user(row: Any) -> SessionUser:
    expires = row.plan_expires_at
    return SessionUser(
        id=row.id,
        username=row.username,
        role=getattr(row.role, "value", row.role),
        plan=getattr(row.plan, "value", row.plan),
        plan_expires_at=expires.isoformat() if expires else None,
        is_active=bool(row.is_active),
        token_version=int(row.token_version or 1),
    )


def issue_user_session(
    secret: str, user_id: int, username: str, token_version: int, ttl_seconds: int
) -> str:
    """Kullanıcı kimlikli imzalı çerez: {uid, sub, ver, exp}."""
    payload = json.dumps(
        {
            "uid": user_id,
            "sub": username,
            "ver": token_version,
            "exp": int(time.time()) + int(ttl_seconds),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


async def verify_user_session(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    config: dict[str, Any],
    token: str | None,
) -> SessionUser | None:
    """Çerezi doğrula ve users satırıyla eşleştir. Eski tek-kullanıcılık
    çerezleri (uid'siz) geçersizdir: bir kez yeniden giriş istenir."""
    if sessionmaker is None or not token or "." not in token:
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
        uid = claims.get("uid")
        if not isinstance(uid, int):
            return None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

    from app.models import User

    async with sessionmaker() as session:
        row = await session.get(User, uid)
    if row is None or not row.is_active:
        return None
    if row.username != claims.get("sub"):
        return None
    if row.token_version != int(claims.get("ver") or -1):
        return None
    return _session_user(row)


def gate_response(feature: str, required_plan: str = "pro") -> JSONResponse:
    """Plana takılan özellik için 403; gövde {detail, feature,
    required_plan} — arayüz upsell notunu bundan kurar."""
    label = FEATURE_LABELS.get(feature, feature)
    return JSONResponse(
        status_code=403,
        content={
            "detail": f"{label} özelliği {required_plan.upper()} planıyla açılır.",
            "feature": feature,
            "required_plan": required_plan,
        },
    )


def user_allows(user: SessionUser | None, feature: str) -> bool:
    """Kapı kararı: açık modda (auth yok) ve admin'de kapı yok; Pro tüm
    özellikleri açar."""
    if user is None or user.is_admin:
        return True
    return user.effective_plan == "pro"


async def ensure_channel_access(request: Request, channel_id: int) -> None:
    """Kanal sahiplik kapısı: kanal yoksa 404; operatör yalnız kendi
    kanalını görür — başkasının kanalı da 404 (varlık sızdırılmaz).
    Admin tüm kanallara erişir; auth kapalıysa (ilk kurulum, testler)
    kapı yok sayılır."""
    user = getattr(request.state, "auth_user", None)
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if user is None or sessionmaker is None:
        return
    from app.models import Channel

    async with sessionmaker() as session:
        channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    if not user.is_admin and channel.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")


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

    async def setup(
        self, username: str, password: str
    ) -> tuple[dict[str, Any], SessionUser]:
        username = username.strip()
        if len(username) < 3 or len(username) > MAX_USERNAME_CHARS:
            raise AuthError("Kullanıcı adı 3-64 karakter olmalı.")
        if len(password) < MIN_PASSWORD_CHARS:
            raise AuthError(
                f"Şifre en az {MIN_PASSWORD_CHARS} karakter olmalı."
            )
        from app.models import AppMeta, User

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
            # İlk hesap users tablosunda da admin olarak yaşar (madde 6).
            user = (
                await session.execute(
                    select(User).where(User.username == username)
                )
            ).scalar_one_or_none()
            if user is None:
                user = User(username=username, password_hash=config["password_hash"])
                session.add(user)
                await session.commit()
            return config, _session_user(user)

    @staticmethod
    def token_for(config: dict[str, Any]) -> str:
        return issue_session(config, str(config["username"]))

    @staticmethod
    def user_token_for(config: dict[str, Any], user: SessionUser) -> str:
        return issue_user_session(
            str(config.get("session_secret") or ""),
            user.id,
            user.username,
            user.token_version,
            int(config.get("session_ttl_seconds") or 7 * 24 * 3600),
        )

    # --- hesap yönetimi (madde 6) ---

    async def get_user_by_credentials(
        self, username: str, password: str
    ) -> SessionUser:
        """users tablosundan doğrula. Tablo boşken studio_auth dönemine
        ait hesap eşleşiyorsa köprüyle users'a admin olarak taşınır."""
        from app.models import User

        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(User).where(User.username == username.strip())
                )
            ).scalar_one_or_none()
            if row is None:
                row = await self._bridge_legacy_user(session, username, password)
            if row is None or not verify_password(password, row.password_hash):
                raise AuthError("Kullanıcı adı veya şifre hatalı.", 401)
            if not row.is_active:
                raise AuthError("Bu hesap devre dışı bırakılmış.", 403)
            return _session_user(row)

    async def _bridge_legacy_user(
        self, session: AsyncSession, username: str, password: str
    ) -> Any:
        """users boşken studio_auth hesabını admin olarak taşır (tek sefer)."""
        from app.models import User

        if (await session.execute(select(User.id))).first() is not None:
            return None
        config = await self.get_config()
        if config is None or not authenticate(config, username, password):
            return None
        user = User(
            username=str(config["username"]),
            password_hash=str(config["password_hash"]),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    async def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> SessionUser:
        from app.models import AppMeta, User

        if len(new_password) < MIN_PASSWORD_CHARS:
            raise AuthError(f"Yeni şifre en az {MIN_PASSWORD_CHARS} karakter olmalı.")
        async with self._sessionmaker() as session:
            row = await session.get(User, user_id)
            if row is None:
                raise AuthError("Kullanıcı bulunamadı.", 404)
            if not verify_password(current_password, row.password_hash):
                raise AuthError("Mevcut şifre hatalı.", 400)
            row.password_hash = hash_password(new_password)
            row.token_version += 1
            # studio_auth meta'sındaki ilk hesapla eşleşiyorsa orayı da
            # güncelle (eski köprü tutarlı kalsın).
            meta = await session.get(AppMeta, AUTH_META_KEY)
            if (
                meta is not None
                and isinstance(meta.value, dict)
                and meta.value.get("username") == row.username
            ):
                meta.value = {**meta.value, "password_hash": row.password_hash}
            await session.commit()
            await session.refresh(row)
            return _session_user(row)

    async def list_users(self) -> list[SessionUser]:
        from app.models import User

        async with self._sessionmaker() as session:
            rows = (
                await session.execute(select(User).order_by(User.id))
            ).scalars()
            return [_session_user(row) for row in rows]

    async def create_user(
        self, username: str, password: str, role: str, plan: str
    ) -> SessionUser:
        from app.models import User, UserPlan, UserRole

        username = username.strip()
        if len(username) < 3 or len(username) > MAX_USERNAME_CHARS:
            raise AuthError("Kullanıcı adı 3-64 karakter olmalı.")
        if len(password) < MIN_PASSWORD_CHARS:
            raise AuthError(f"Şifre en az {MIN_PASSWORD_CHARS} karakter olmalı.")
        try:
            role_value = UserRole(role)
            plan_value = UserPlan(plan)
        except ValueError:
            raise AuthError("Geçersiz rol ya da plan.") from None
        async with self._sessionmaker() as session:
            exists = (
                await session.execute(
                    select(User.id).where(User.username == username)
                )
            ).first()
            if exists is not None:
                raise AuthError("Bu kullanıcı adı zaten alınmış.", 409)
            row = User(
                username=username,
                password_hash=hash_password(password),
                role=role_value,
                plan=plan_value,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _session_user(row)

    async def patch_user(
        self,
        user_id: int,
        *,
        role: str | None = None,
        plan: str | None = None,
        is_active: bool | None = None,
    ) -> SessionUser:
        from app.models import User, UserPlan, UserRole

        async with self._sessionmaker() as session:
            row = await session.get(User, user_id)
            if row is None:
                raise AuthError("Kullanıcı bulunamadı.", 404)
            new_role = UserRole(role) if role is not None else row.role
            if role is not None:
                try:
                    new_role = UserRole(role)
                except ValueError:
                    raise AuthError("Geçersiz rol.") from None
            new_active = is_active if is_active is not None else row.is_active
            # Son etkin yönetici düşürülemez ya da kapatılamaz.
            if row.role == UserRole.admin and (
                new_role != UserRole.admin or not new_active
            ):
                others = (
                    await session.execute(
                        select(User.id).where(
                            User.role == UserRole.admin,
                            User.is_active.is_(True),
                            User.id != row.id,
                        )
                    )
                ).first()
                if others is None:
                    raise AuthError(
                        "Son yöneticinin rolü düşürülemez ya da hesabı kapatılamaz."
                    )
            if plan is not None:
                try:
                    row.plan = UserPlan(plan)
                except ValueError:
                    raise AuthError("Geçersiz plan.") from None
            if role is not None:
                row.role = new_role
            if is_active is not None:
                row.is_active = new_active
            await session.commit()
            await session.refresh(row)
            return _session_user(row)

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

        if getattr(request.app.state, "auth_db_error", False):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Veritabanı bağlantısı kurulamadı; güvenlik nedeniyle API kilitlendi."
                },
            )

        config = getattr(request.app.state, "auth_config", None)
        if config is None:
            # İlk kurulum öncesi (veya DB'siz geliştirme) API açıktır;
            # parola oluşturulduğu anda bu dal kapanır.
            return await call_next(request)

        user = await verify_user_session(
            getattr(request.app.state, "sessionmaker", None),
            config,
            request.cookies.get(SESSION_COOKIE),
        )
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Oturum gerekli."},
            )
        request.state.auth_user = user
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
