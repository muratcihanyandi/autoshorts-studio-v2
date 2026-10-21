"""YouTube resumable upload client (M10).

Official Data API only. Flow (resumable protocol):
1. POST /upload/youtube/v3/videos?uploadType=resumable with metadata
   (snippet + status) -> session URI in the Location header.
2. PUT the media bytes to the session URI (one request for the whole
   file; the session URI itself is the recovery handle).
3. videos.list?part=status verifies the stored privacy status.

Access tokens arrive through OAuthService.access_token (refreshed,
in-memory only). Every clip uploads as private first; visibility
changes are an explicit later step. All calls go through an injectable
httpx client so tests run against a faithful MockTransport.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_TIMEOUT = 600.0


class UploadError(Exception):
    """Upload failure with a user-facing Turkish message."""


@dataclass
class UploadResult:
    video_id: str
    session_uri: str
    title: str


@dataclass
class VideoStatus:
    privacy_status: str
    upload_status: str


class YouTubeUploadClient:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def start_session(
        self,
        http: httpx.AsyncClient,
        *,
        title: str,
        description: str,
        tags: list[str],
    ) -> str:
        """Open a resumable session; returns the session URI."""
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
            },
        }
        response = await http.post(
            f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=body,
        )
        if response.status_code not in (200, 201):
            raise UploadError(
                f"Yukleme oturumu acilamadi (HTTP {response.status_code})."
            )
        session_uri = response.headers.get("location")
        if not session_uri:
            raise UploadError("Yukleme oturum adresi donmedi.")
        return session_uri

    async def upload_file(
        self,
        http: httpx.AsyncClient,
        session_uri: str,
        file_path: str | Path,
    ) -> str:
        """PUT the media bytes; returns the YouTube video id."""
        path = Path(file_path)
        if not path.is_file():
            raise UploadError(f"Yuklenecek dosya yok: {path}")
        data = await _read_bytes(path)
        response = await http.put(
            session_uri,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(data)),
            },
            content=data,
        )
        if response.status_code not in (200, 201):
            raise UploadError(
                f"Dosya yuklenemedi (HTTP {response.status_code})."
            )
        try:
            video_id = response.json()["id"]
        except (ValueError, KeyError) as exc:
            raise UploadError("Yukleme yanitinda video kimligi yok.") from exc
        return video_id

    async def set_privacy_public(
        self, http: httpx.AsyncClient, video_id: str
    ) -> None:
        """videos.update ile gorunurlugu herkese acik yap (zamanli
        yayin adimi: yukleme her zaman gizlidir, acilis plan saatinde
        burada gerceklesir)."""
        await self.set_privacy(http, video_id, "public")

    async def set_privacy(
        self, http: httpx.AsyncClient, video_id: str, privacy: str
    ) -> None:
        """videos.update ile gorunurlugu degistir ('public'/'private').
        Toplu kütüphane eylemlerinin gizliye alma kolu da buradan
        gecer; degisiklik fetch_status ile ayri dogrulanir."""
        if privacy not in ("public", "private"):
            raise UploadError("Gecersiz gorunurluk degeri.")
        response = await http.put(
            f"{VIDEOS_URL}?part=status",
            headers=self._headers(),
            json={
                "id": video_id,
                "status": {"privacyStatus": privacy},
            },
        )
        if response.status_code not in (200, 201):
            raise UploadError(
                f"Video gorunurlugu degistirilemedi (HTTP {response.status_code})."
            )

    async def delete_video(
        self, http: httpx.AsyncClient, video_id: str
    ) -> None:
        """videos.delete — klibi YouTube uzerinden kalici siler (kullanici
        istegi 2026-10-21: kaldirilan klip once YouTube'dan silinir).
        404 'zaten yok' sayilir; force-ssl kapsami ister."""
        response = await http.delete(
            VIDEOS_URL,
            params={"id": video_id},
            headers=self._headers(),
        )
        if response.status_code not in (200, 204, 404):
            raise UploadError(
                f"Video YouTube'dan silinemedi (HTTP {response.status_code})."
            )

    async def fetch_status(
        self, http: httpx.AsyncClient, video_id: str
    ) -> VideoStatus:
        """videos.list?part=status — visibility verification."""
        response = await http.get(
            f"{VIDEOS_URL}?part=status&id={video_id}",
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise UploadError(
                f"Video durugu okunamadi (HTTP {response.status_code})."
            )
        items = response.json().get("items", [])
        if not items:
            raise UploadError("Video YouTube uzerinde bulunamadi.")
        status = items[0].get("status", {})
        return VideoStatus(
            privacy_status=str(status.get("privacyStatus", "")),
            upload_status=str(status.get("uploadStatus", "")),
        )


async def _read_bytes(path: Path) -> bytes:
    import asyncio

    return await asyncio.to_thread(path.read_bytes)
