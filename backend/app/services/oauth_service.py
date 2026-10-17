"""Google/YouTube OAuth handshake for channels.

Flow: start -> single-use state -> callback (code exchange + channel
lookup) -> encrypted credential storage. Tokens live only in
oauth_credentials, encrypted with the configured Fernet key, and never
appear in API responses.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Channel, ChannelStatus, OAuthCredential, OAuthState
from app.security import TokenCipher
from app.services.channel_service import record_event

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.readonly"
)
STATE_TTL_MINUTES = 10
TOKEN_EXPIRY_SKEW_SECONDS = 60


class OAuthError(Exception):
    """Flow failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _default_http_client() -> httpx.AsyncClient:
    """Indirection point so tests can inject a mock transport."""
    return httpx.AsyncClient(timeout=15)


def _as_utc(value: datetime) -> datetime:
    """sqlite naive datetime'lerini UTC'ye taşır (asyncpg zaten farkında döner)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class OAuthService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._cipher_instance: TokenCipher | None = None

    @property
    def _cipher(self) -> TokenCipher:
        """Tembel: anahtar yapılandırılmamışsa kurucu hata vermez."""
        if self._cipher_instance is None:
            if not self._settings.token_encryption_key:
                raise OAuthError(
                    "TOKEN_ENCRYPTION_KEY yapılandırılmamış.", status_code=503
                )
            self._cipher_instance = TokenCipher(self._settings.token_encryption_key)
        return self._cipher_instance

    def _redirect_uri(self, channel_id: int) -> str:
        return (
            f"{self._settings.oauth_redirect_base.rstrip('/')}"
            f"/api/channels/{channel_id}/oauth/callback"
        )

    async def start(self, channel_id: int) -> dict[str, str]:
        """Create a single-use state and return the authorization URL."""
        if not self._settings.oauth_configured:
            raise OAuthError(
                "Google OAuth istemci bilgileri yapılandırılmamış "
                "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / TOKEN_ENCRYPTION_KEY).",
                status_code=503,
            )
        async with self._sessionmaker() as session:
            channel = await session.get(Channel, channel_id)
            if channel is None:
                raise OAuthError("Kanal bulunamadı.", status_code=404)

            state = secrets.token_urlsafe(32)
            session.add(
                OAuthState(
                    state=state,
                    channel_id=channel_id,
                    expires_at=datetime.now(UTC) + timedelta(minutes=STATE_TTL_MINUTES),
                )
            )
            record_event(session, channel_id, "oauth.started")
            await session.commit()

        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": self._redirect_uri(channel_id),
            "response_type": "code",
            "scope": OAUTH_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}

    async def _validate_state(self, session: AsyncSession, channel_id: int, state: str) -> OAuthState:
        row = await session.get(OAuthState, state)
        now = datetime.now(UTC)
        if row is None or row.channel_id != channel_id:
            raise OAuthError("Geçersiz OAuth durumu (state).")
        if row.consumed_at is not None:
            raise OAuthError("Bu OAuth durumu daha önce kullanılmış.")
        if _as_utc(row.expires_at) < now:
            raise OAuthError("OAuth durumunun süresi dolmuş; bağlantıyı yeniden başlat.")
        row.consumed_at = now
        return row

    async def _exchange_code(
        self, http: httpx.AsyncClient, channel_id: int, code: str
    ) -> dict:
        response = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret,
                "redirect_uri": self._redirect_uri(channel_id),
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            raise OAuthError("Google kod değişimi başarısız oldu.")
        return response.json()

    async def _fetch_youtube_channel(
        self, http: httpx.AsyncClient, access_token: str
    ) -> dict:
        response = await http.get(
            YOUTUBE_CHANNELS_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            raise OAuthError("YouTube kanal bilgisi alınamadı.")
        items = response.json().get("items") or []
        if not items:
            raise OAuthError("Bu Google hesabına bağlı bir YouTube kanalı yok.")
        snippet = items[0].get("snippet", {})
        return {
            "id": items[0].get("id"),
            "title": snippet.get("title", ""),
            "custom_url": snippet.get("customUrl"),
        }

    async def callback(
        self,
        channel_id: int,
        code: str | None,
        state: str | None,
        error: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> Channel:
        """Validate the state, exchange the code, store encrypted tokens."""
        async with self._sessionmaker() as session:
            channel = await session.get(Channel, channel_id)
            if channel is None:
                raise OAuthError("Kanal bulunamadı.", status_code=404)

            if error is not None:
                record_event(session, channel_id, "oauth.failed", {"reason": error})
                await session.commit()
                raise OAuthError(f"Google yetkilendirmesi reddedildi: {error}.")

            if not code or not state:
                raise OAuthError("Eksik code/state parametresi.")

            await self._validate_state(session, channel_id, state)

            client = http or _default_http_client()
            try:
                tokens = await self._exchange_code(client, channel_id, code)
                yt_channel = await self._fetch_youtube_channel(
                    client, tokens["access_token"]
                )
            finally:
                if http is None:
                    await client.aclose()

            youtube_channel_id = yt_channel["id"]
            existing = (
                await session.execute(
                    select(Channel).where(
                        Channel.youtube_channel_id == youtube_channel_id,
                        Channel.id != channel_id,
                    )
                )
            ).scalars().one_or_none()
            if existing is not None:
                record_event(
                    session,
                    channel_id,
                    "oauth.failed",
                    {"reason": "duplicate_youtube_channel"},
                )
                await session.commit()
                raise OAuthError(
                    "Bu YouTube kanalı zaten başka bir stüdyo kanalına bağlı."
                )

            expires_in = tokens.get("expires_in")
            credential = (
                await session.execute(
                    select(OAuthCredential).where(
                        OAuthCredential.channel_id == channel_id
                    )
                )
            ).scalars().one_or_none()
            if credential is None:
                credential = OAuthCredential(channel_id=channel_id)
                session.add(credential)
            credential.provider = "youtube"
            credential.access_token_enc = self._cipher.encrypt(tokens["access_token"])
            if tokens.get("refresh_token"):
                credential.refresh_token_enc = self._cipher.encrypt(
                    tokens["refresh_token"]
                )
            credential.token_expires_at = (
                datetime.now(UTC) + timedelta(seconds=expires_in)
                if expires_in
                else None
            )
            credential.scope = tokens.get("scope", OAUTH_SCOPES)

            channel.youtube_channel_id = youtube_channel_id
            channel.status = ChannelStatus.connected
            channel.last_connected_at = datetime.now(UTC)
            if not channel.handle and yt_channel.get("custom_url"):
                channel.handle = yt_channel["custom_url"]

            record_event(
                session,
                channel_id,
                "oauth.connected",
                {"youtube_channel_id": youtube_channel_id},
            )
            await session.commit()
            await session.refresh(channel)
            return channel

    async def refresh_if_needed(
        self, channel_id: int, http: httpx.AsyncClient | None = None
    ) -> bool:
        """Refresh the access token when it is missing or about to expire."""
        async with self._sessionmaker() as session:
            credential = (
                await session.execute(
                    select(OAuthCredential).where(
                        OAuthCredential.channel_id == channel_id
                    )
                )
            ).scalars().one_or_none()
            if credential is None or not credential.refresh_token_enc:
                return False
            now = datetime.now(UTC)
            if (
                credential.token_expires_at is not None
                and _as_utc(credential.token_expires_at)
                > now + timedelta(seconds=TOKEN_EXPIRY_SKEW_SECONDS)
            ):
                return False

            # Şifreli depodan çözülen token yalnızca Google'ın token ucuna gider.
            refresh_token = self._cipher.decrypt(credential.refresh_token_enc)  # secret-scan-ok
            client = http or _default_http_client()
            try:
                response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self._settings.google_client_id,
                        "client_secret": self._settings.google_client_secret,
                        "refresh_token": refresh_token,  # secret-scan-ok: Google token ucu
                        "grant_type": "refresh_token",
                    },
                )
            finally:
                if http is None:
                    await client.aclose()
            if response.status_code != 200:
                record_event(session, channel_id, "oauth.token_refresh_failed")
                await session.commit()
                return False

            tokens = response.json()
            credential.access_token_enc = self._cipher.encrypt(tokens["access_token"])
            if tokens.get("expires_in"):
                credential.token_expires_at = now + timedelta(
                    seconds=tokens["expires_in"]
                )
            record_event(session, channel_id, "oauth.token_refreshed")
            await session.commit()
            return True
