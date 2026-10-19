"""Character CRUD + photo endpoints tests (M13, workstream A).

Photo uploads run real OpenCV: a synthetic gradient png (no face) and
the committed public-domain face fixture. Raw file paths must never
appear in any API response; the photo endpoint serves the bytes.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from tests.conftest import _make_app

FACE_FIXTURE = Path(__file__).parent / "assets" / "face_pd.jpg"
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def _make_character_client(tmp_path, **overrides) -> TestClient:
    """media_root'lü uygulama; fotoğraf testleri tmp_path altına yazar."""
    media_root = overrides.pop("media_root", str(tmp_path / "medya"))
    app = _make_app(tmp_path, media_root=media_root, **overrides)
    client = TestClient(app)
    client.__enter__()
    return client


def _gradient_png() -> bytes:
    """Yüz içermeyen sentetik png (düz gri gradyan)."""
    grad = np.tile(np.linspace(0, 255, 320, dtype=np.uint8), (240, 1))
    frame = cv2.merge([grad, grad, grad])
    ok, buffer = cv2.imencode(".png", frame)
    assert ok
    return buffer.tobytes()


def _create(client: TestClient, name: str = "Yayıncı Bir", **extra) -> dict:
    response = client.post("/api/characters", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


# --- CRUD ---


def test_characters_require_database(client_no_db: TestClient) -> None:
    assert client_no_db.get("/api/characters").status_code == 503


def test_create_list_get_patch_delete(client_db: TestClient) -> None:
    created = client_db.post(
        "/api/characters",
        json={
            "name": "Yayıncı Bir",
            "system_prompt": "Tokatlı, esprili anlatım kullan.",
            "notes": "Sabit yayın günleri",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Yayıncı Bir"
    assert body["photo_configured"] is False
    assert body["reference_face"] is False
    assert body["system_prompt_set"] is True
    assert body["notes"] == "Sabit yayın günleri"
    assert body["created_at"] is not None
    # Ham dosya yolları ve prompt metni asla yanıtta olmamalı.
    assert "photo_path" not in body
    assert "reference_face_path" not in body
    assert "system_prompt" not in body

    listing = client_db.get("/api/characters").json()
    assert listing == {"characters": [body], "total": 1}

    assert client_db.get(f"/api/characters/{body['id']}").json() == body

    renamed = client_db.patch(
        f"/api/characters/{body['id']}", json={"name": "Yeni Ad"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Yeni Ad"
    assert renamed.json()["system_prompt_set"] is True

    cleared = client_db.patch(
        f"/api/characters/{body['id']}", json={"system_prompt": ""}
    )
    assert cleared.status_code == 200
    assert cleared.json()["system_prompt_set"] is False

    assert client_db.delete(f"/api/characters/{body['id']}").status_code == 204
    assert client_db.get(f"/api/characters/{body['id']}").status_code == 404
    assert (
        client_db.patch(f"/api/characters/{body['id']}", json={"name": "X"}).status_code
        == 404
    )
    assert client_db.delete(f"/api/characters/{body['id']}").status_code == 404


def test_create_without_optional_fields(client_db: TestClient) -> None:
    body = _create(client_db, "Sade İsim")
    assert body["system_prompt_set"] is False
    assert body["notes"] is None


def test_duplicate_name_rejected(client_db: TestClient) -> None:
    _create(client_db, "Aynı İsim")
    duplicate = client_db.post("/api/characters", json={"name": "Aynı İsim"})
    assert duplicate.status_code == 409


def test_rename_to_existing_name_rejected(client_db: TestClient) -> None:
    first = _create(client_db, "Birinci")
    second = _create(client_db, "İkinci")
    response = client_db.patch(
        f"/api/characters/{second['id']}", json={"name": first["name"]}
    )
    assert response.status_code == 409


def test_create_validates_name(client_db: TestClient) -> None:
    assert client_db.post("/api/characters", json={"name": ""}).status_code == 422
    assert (
        client_db.post("/api/characters", json={"name": "x" * 121}).status_code == 422
    )


# --- Photo ---


def test_photo_upload_requires_media_root(tmp_path) -> None:
    client = _make_character_client(tmp_path, media_root="")
    try:
        character = _create(client)
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("foto.png", _gradient_png(), "image/png")},
        )
        assert response.status_code == 503
        assert "MEDYA" in response.json()["detail"].upper()
    finally:
        client.__exit__(None, None, None)


def test_photo_upload_stores_png_without_face(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        png = _gradient_png()
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("foto.png", png, "image/png")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["photo_configured"] is True
        assert body["reference_face"] is False
        assert "photo_path" not in body

        media_root = Path(client.app.state.settings.media_root)
        stored = list((media_root / "characters").glob(f"{character['id']}_*.png"))
        assert len(stored) == 1
        assert stored[0].read_bytes() == png
        # Yüz yoksa referans dosyası da yok.
        assert not (media_root / "characters" / f"{character['id']}_ref.png").exists()

        served = client.get(f"/api/characters/{character['id']}/photo")
        assert served.status_code == 200
        assert served.content == png
        assert served.headers["content-type"].startswith("image/png")
    finally:
        client.__exit__(None, None, None)


def test_photo_upload_extracts_reference_face(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        fixture = FACE_FIXTURE.read_bytes()
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("yuz.jpg", fixture, "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["photo_configured"] is True
        assert body["reference_face"] is True

        media_root = Path(client.app.state.settings.media_root)
        ref_path = media_root / "characters" / f"{character['id']}_ref.png"
        assert ref_path.is_file()
        crop = cv2.imread(str(ref_path))
        assert crop is not None
        # Kırpma yüz boyutunda olmalı (tam fotoğraf değil).
        assert 0 < crop.shape[0] <= 400
        assert 0 < crop.shape[1] <= 400

        served = client.get(f"/api/characters/{character['id']}/photo")
        assert served.status_code == 200
        assert served.content == fixture
        assert served.headers["content-type"].startswith("image/jpeg")
    finally:
        client.__exit__(None, None, None)


def test_photo_reupload_without_face_clears_reference(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        upload = lambda data, name: client.post(  # noqa: E731
            f"/api/characters/{character['id']}/photo",
            files={"file": (name, data, "application/octet-stream")},
        )
        assert upload(FACE_FIXTURE.read_bytes(), "yuz.jpg").json()["reference_face"] is True
        replaced = upload(_gradient_png(), "yeni.png")
        assert replaced.status_code == 200
        assert replaced.json()["reference_face"] is False
        assert replaced.json()["photo_configured"] is True
    finally:
        client.__exit__(None, None, None)


def test_photo_oversized_rejected(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_PHOTO_BYTES - 8)
        assert len(oversized) == MAX_PHOTO_BYTES
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("buyuk.png", oversized + b"x", "image/png")},
        )
        assert response.status_code == 400
        assert client.get(f"/api/characters/{character['id']}/photo").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_photo_non_image_rejected(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("not.png", b"bu bir resim degil", "image/png")},
        )
        assert response.status_code == 400
    finally:
        client.__exit__(None, None, None)


def test_photo_unsupported_image_type_rejected(tmp_path) -> None:
    """cv2 bmp'yi cozebilir; yalnizca jpg/png/webp kabul edilmeli."""
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        grad = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
        ok, buffer = cv2.imencode(".bmp", cv2.merge([grad, grad, grad]))
        assert ok
        response = client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("resim.bmp", buffer.tobytes(), "image/bmp")},
        )
        assert response.status_code == 400
    finally:
        client.__exit__(None, None, None)


def test_photo_missing_character_404(client_db: TestClient) -> None:
    response = client_db.post(
        "/api/characters/999/photo",
        files={"file": ("foto.png", _gradient_png(), "image/png")},
    )
    assert response.status_code == 404


def test_photo_get_unset_or_missing_file_404(tmp_path) -> None:
    client = _make_character_client(tmp_path)
    try:
        character = _create(client)
        # Henüz fotoğraf yok.
        assert client.get(f"/api/characters/{character['id']}/photo").status_code == 404

        client.post(
            f"/api/characters/{character['id']}/photo",
            files={"file": ("foto.png", _gradient_png(), "image/png")},
        )
        # Kayıt var ama diskteki dosya silindi.
        stored = list(
            (Path(client.app.state.settings.media_root) / "characters").glob(
                f"{character['id']}_*.png"
            )
        )
        stored[0].unlink()
        assert client.get(f"/api/characters/{character['id']}/photo").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_photo_get_missing_character_404(client_db: TestClient) -> None:
    assert client_db.get("/api/characters/999/photo").status_code == 404
