"""Character management API (M13): streamer personas + photos.

Responses carry masked views only -- raw photo/reference-face file
paths and prompt text stay server-side; the photo endpoint serves the
bytes.
"""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.schemas_characters import (
    CharacterCreate,
    CharacterOut,
    CharactersOut,
    CharacterUpdate,
)
from app.services.character_service import CharacterService, CharacterServiceError

router = APIRouter(tags=["characters"])


def _service(request: Request) -> CharacterService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; karakter yönetimi kapalı.",
        )
    return CharacterService(sessionmaker, request.app.state.settings)


def _out_or_404(character) -> CharacterOut:
    if character is None:
        raise HTTPException(status_code=404, detail="Karakter bulunamadı.")
    return CharacterOut.from_character(character)


@router.get("/characters", response_model=CharactersOut)
async def list_characters(request: Request) -> CharactersOut:
    service = _service(request)
    characters = await service.list_characters()
    return CharactersOut(
        characters=[CharacterOut.from_character(c) for c in characters],
        total=len(characters),
    )


@router.post(
    "/characters",
    response_model=CharacterOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_character(request: Request, data: CharacterCreate) -> CharacterOut:
    service = _service(request)
    try:
        character = await service.create_character(data)
    except CharacterServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return CharacterOut.from_character(character)


@router.get("/characters/{character_id}", response_model=CharacterOut)
async def get_character(request: Request, character_id: int) -> CharacterOut:
    service = _service(request)
    return _out_or_404(await service.get_character(character_id))


@router.patch("/characters/{character_id}", response_model=CharacterOut)
async def update_character(
    request: Request, character_id: int, data: CharacterUpdate
) -> CharacterOut:
    service = _service(request)
    try:
        character = await service.update_character(character_id, data)
    except CharacterServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _out_or_404(character)


@router.delete(
    "/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_character(request: Request, character_id: int) -> None:
    service = _service(request)
    if not await service.delete_character(character_id):
        raise HTTPException(status_code=404, detail="Karakter bulunamadı.")


@router.post(
    "/characters/{character_id}/photo", response_model=CharacterOut
)
async def upload_photo(
    request: Request, character_id: int, file: UploadFile = File(...)
) -> CharacterOut:
    """Validate the upload (jpg/png/webp, <=8MB) and refresh the stored
    photo plus the cropped reference face."""
    service = _service(request)
    data = await file.read()
    try:
        character = await service.set_photo(character_id, data)
    except CharacterServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return CharacterOut.from_character(character)


@router.get("/characters/{character_id}/photo")
async def get_photo(request: Request, character_id: int) -> FileResponse:
    service = _service(request)
    character = await service.get_character(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Karakter bulunamadı.")
    path = service.photo_file(character)
    if path is None:
        raise HTTPException(status_code=404, detail="Karakter fotoğrafı yok.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)
