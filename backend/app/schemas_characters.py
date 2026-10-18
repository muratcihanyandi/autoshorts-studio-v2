"""Character schemas (M13): streamer personas bound to source channels.

Photo/reference-face file paths and the raw system prompt are
server-side only: responses carry `photo_configured` /
`reference_face` / `system_prompt_set` flags; the photo endpoint
serves the bytes.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    system_prompt: str | None = None
    notes: str | None = None


class CharacterUpdate(BaseModel):
    """PATCH semantics: only sent fields change. A blank system_prompt
    string clears the per-character prompt (falls back to the global)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    system_prompt: str | None = None
    notes: str | None = None


class CharacterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    photo_configured: bool
    reference_face: bool
    system_prompt_set: bool
    notes: str | None
    created_at: datetime

    @classmethod
    def from_character(cls, character) -> "CharacterOut":
        """Masked view: derived flags only, never raw paths or prompt."""
        return cls(
            id=character.id,
            name=character.name,
            photo_configured=bool(character.photo_path),
            reference_face=bool(character.reference_face_path),
            system_prompt_set=bool(character.system_prompt),
            notes=character.notes,
            created_at=character.created_at,
        )


class CharactersOut(BaseModel):
    characters: list[CharacterOut]
    total: int
