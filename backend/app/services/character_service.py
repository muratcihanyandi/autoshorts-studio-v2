"""Character service: streamer personas + photo/reference-face storage.

A character binds N source channels across platforms (M13). The
uploaded photo is stored under MEDIA_ROOT/characters and the largest
Haar-detected face is cropped (20% padding) as the reference face for
webcam validation; a photo without a detectable face keeps the
reference unset. Raw file paths never leave this layer.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Character
from app.schemas_characters import CharacterCreate, CharacterUpdate
from app.services.channel_service import record_event
from app.services.webcam_detect import HaarFaceDetector

MAX_PHOTO_BYTES = 8 * 1024 * 1024
REFERENCE_FACE_PADDING = 0.2


class CharacterServiceError(Exception):
    """Business rule failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _photo_extension(data: bytes) -> str | None:
    """Content sniffing: only jpg/png/webp photos are accepted."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class CharacterService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._detector = HaarFaceDetector()

    async def list_characters(self) -> list[Character]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(Character).order_by(Character.created_at, Character.id)
            )
            return list(result.scalars().all())

    async def get_character(self, character_id: int) -> Character | None:
        async with self._sessionmaker() as session:
            return await session.get(Character, character_id)

    async def create_character(self, data: CharacterCreate) -> Character:
        async with self._sessionmaker() as session:
            clash = (
                await session.execute(
                    select(Character.id).where(Character.name == data.name)
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise CharacterServiceError(
                    "Bu karakter adı zaten kayıtlı.", status_code=409
                )
            character = Character(
                name=data.name,
                system_prompt=data.system_prompt or None,
                notes=data.notes or None,
            )
            session.add(character)
            await session.flush()
            record_event(session, None, "character.created", {"name": data.name})
            await session.commit()
            await session.refresh(character)
            return character

    async def update_character(
        self, character_id: int, data: CharacterUpdate
    ) -> Character | None:
        async with self._sessionmaker() as session:
            character = await session.get(Character, character_id)
            if character is None:
                return None
            changes = data.model_dump(exclude_unset=True)
            if "name" in changes and changes["name"] != character.name:
                clash = (
                    await session.execute(
                        select(Character.id).where(
                            Character.name == changes["name"],
                            Character.id != character_id,
                        )
                    )
                ).scalar_one_or_none()
                if clash is not None:
                    raise CharacterServiceError(
                        "Bu karakter adı zaten kayıtlı.", status_code=409
                    )
                character.name = changes["name"]
            # Bos prompt/not metni kaydi temizler (genel davranisa doner).
            if "system_prompt" in changes:
                character.system_prompt = changes["system_prompt"] or None
            if "notes" in changes:
                character.notes = changes["notes"] or None
            if changes:
                record_event(
                    session,
                    None,
                    "character.updated",
                    {"character_id": character_id, "fields": sorted(changes)},
                )
                await session.commit()
                await session.refresh(character)
            return character

    async def delete_character(self, character_id: int) -> bool:
        async with self._sessionmaker() as session:
            character = await session.get(Character, character_id)
            if character is None:
                return False
            record_event(session, None, "character.deleted", {"name": character.name})
            await session.flush()
            await session.delete(character)
            await session.commit()
            return True

    async def set_photo(self, character_id: int, data: bytes) -> Character:
        """Validate the upload, store the photo, refresh the reference
        face (largest detected face, 20% padding; None without a face)."""
        async with self._sessionmaker() as session:
            character = await session.get(Character, character_id)
            if character is None:
                raise CharacterServiceError(
                    "Karakter bulunamadı.", status_code=404
                )
            if not self._settings.media_root:
                raise CharacterServiceError(
                    "Medya klasörü (MEDIA_ROOT) yapılandırılmadı; "
                    "fotoğraf yükleme kapalı.",
                    status_code=503,
                )
            if len(data) > MAX_PHOTO_BYTES:
                raise CharacterServiceError(
                    "Fotoğraf en fazla 8 MB olabilir.", status_code=400
                )
            extension = _photo_extension(data)
            if extension is None:
                raise CharacterServiceError(
                    "Fotoğraf yalnızca jpg, png veya webp biçiminde olabilir.",
                    status_code=400,
                )
            image = cv2.imdecode(
                np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                raise CharacterServiceError(
                    "Fotoğraf dosyası okunamadı; dosya bozuk olabilir.",
                    status_code=400,
                )

            media_root = Path(self._settings.media_root)
            characters_dir = media_root / "characters"
            characters_dir.mkdir(parents=True, exist_ok=True)

            sha8 = hashlib.sha256(data).hexdigest()[:8]
            photo_rel = f"characters/{character_id}_{sha8}.{extension}"
            (media_root / photo_rel).write_bytes(data)

            reference_rel = self._extract_reference_face(
                character_id, image, characters_dir
            )
            character.photo_path = photo_rel
            character.reference_face_path = reference_rel
            record_event(
                session,
                None,
                "character.photo_updated",
                {
                    "character_id": character_id,
                    "reference_face": reference_rel is not None,
                },
            )
            await session.commit()
            await session.refresh(character)
            return character

    def _extract_reference_face(
        self, character_id: int, image, characters_dir: Path
    ) -> str | None:
        """Crop the largest detected face with 20% padding; None when
        the photo has no detectable face."""
        faces = self._detector.detect(image)
        if not faces:
            return None
        x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
        pad_x = int(w * REFERENCE_FACE_PADDING)
        pad_y = int(h * REFERENCE_FACE_PADDING)
        x0 = max(0, x - pad_x)
        y0 = max(0, y - pad_y)
        x1 = min(image.shape[1], x + w + pad_x)
        y1 = min(image.shape[0], y + h + pad_y)
        crop = image[y0:y1, x0:x1]
        target = characters_dir / f"{character_id}_ref.png"
        if not cv2.imwrite(str(target), crop):
            raise CharacterServiceError(
                "Referans yüz dosyası kaydedilemedi.", status_code=500
            )
        return f"characters/{character_id}_ref.png"

    def photo_file(self, character: Character) -> Path | None:
        """Absolute path of the stored photo when the file exists."""
        if not character.photo_path or not self._settings.media_root:
            return None
        path = Path(self._settings.media_root) / character.photo_path
        return path if path.is_file() else None
