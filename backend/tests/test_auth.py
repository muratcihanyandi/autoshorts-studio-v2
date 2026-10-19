"""Studio login: first-run setup, session cookie, API gate."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import _make_app


def _setup(client: TestClient, username: str = "murat", password: str = "gizli-sifre"):
    return client.post(
        "/api/auth/setup",
        json={"username": username, "password": password},  # secret-scan-ok
    )


def test_api_open_before_first_setup(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        status = client.get("/api/auth/status").json()
        assert status == {
            "configured": False,
            "authenticated": False,
            "username": None,
        }
        # Kurulum öncesi ürün açılabilir; parola oluşturulunca kapı kapanır.
        assert client.get("/api/system").status_code == 200


def test_setup_creates_session_and_protects_api(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        response = _setup(client)
        assert response.status_code == 201, response.text
        assert response.json()["authenticated"] is True

        status = client.get("/api/auth/status").json()
        assert status["configured"] is True
        assert status["authenticated"] is True
        assert status["username"] == "murat"
        # Parola veya oturum sırrı hiçbir yanıtta dönmez.
        assert "password" not in response.text.lower()
        assert "secret" not in response.text.lower()

        assert client.get("/api/system").status_code == 200
        client.post("/api/auth/logout")
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.get("/api/system").status_code == 401


def test_login_rejects_wrong_password_and_accepts_right_one(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        _setup(client, password="dogru-sifre")  # secret-scan-ok
        client.post("/api/auth/logout")

        wrong = client.post(
            "/api/auth/login",
            json={"username": "murat", "password": "yanlis-sifre"},  # secret-scan-ok
        )
        assert wrong.status_code == 401
        assert client.get("/api/system").status_code == 401

        right = client.post(
            "/api/auth/login",
            json={"username": "murat", "password": "dogru-sifre"},  # secret-scan-ok
        )
        assert right.status_code == 200
        assert right.json()["authenticated"] is True
        assert client.get("/api/system").status_code == 200


def test_setup_cannot_run_twice(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        assert _setup(client).status_code == 201
        second = _setup(client, password="baska-sifre")  # secret-scan-ok
        assert second.status_code == 409


def test_setup_validates_short_password(tmp_path):
    with TestClient(_make_app(tmp_path)) as client:
        response = _setup(client, password="kisa")
        assert response.status_code == 400
        assert client.get("/api/auth/status").json()["configured"] is False
