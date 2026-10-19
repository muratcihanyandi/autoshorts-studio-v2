"""Whisper runtime installation: platform plans, availability probes,
subprocess env composition, the install API flow, and the transcriber
command contract.

pip never runs in tests — the install subprocess is faked; the goal is
to verify the platform decision logic, the honest state machine, and
the guards (400 already installed, 409 double start, 503 disk).
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from tests.conftest import _make_app


def _env(tmp_path, **overrides):
    db_path = tmp_path / "winstall.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        media_root=str(tmp_path / "media"),
        **overrides,
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    return sessionmaker, settings, engine


class TestInstallPlan:
    def test_windows_direct(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi.platform_mod, "system", lambda: "Windows")
        sessionmaker, settings, engine = _env(tmp_path)
        try:
            plan = wi.plan_install(settings)
        finally:
            asyncio.run(engine.dispose())
        assert plan["mode"] == "direct"
        assert plan["target"] is None
        assert plan["cmd"][:4] == [sys.executable, "-m", "pip", "install"]
        assert wi.WHISPER_PACKAGE in plan["cmd"]
        assert "--target" not in plan["cmd"]
        assert plan["env"] == {}

    def test_linux_targets_media_tree(self, tmp_path, monkeypatch):
        """Pi konteyneri: uid 1000 + root'a ait site-packages -> kurulum
        kalici medya agacina --target ile, cagrilar PYTHONPATH ile."""
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi.platform_mod, "system", lambda: "Linux")
        sessionmaker, settings, engine = _env(tmp_path)
        try:
            plan = wi.plan_install(settings)
        finally:
            asyncio.run(engine.dispose())
        assert plan["mode"] == "target"
        assert plan["target"] == str(tmp_path / "media" / ".whisper")
        assert "--target" in plan["cmd"]
        assert wi.WHISPER_PACKAGE in plan["cmd"]
        assert plan["env"]["PYTHONPATH"] == str(tmp_path / "media" / ".whisper")

    def test_linux_without_media_root_falls_back_direct(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi.platform_mod, "system", lambda: "Linux")
        db_path = tmp_path / "n.db"
        sync_engine = sa.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")
        plan = wi.plan_install(settings)
        assert plan["mode"] == "direct"
        assert "--target" not in plan["cmd"]


class TestAvailability:
    def test_available_via_target_dir(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        sessionmaker, settings, engine = _env(tmp_path)
        try:
            monkeypatch.setattr(wi, "_spec_available", lambda: False)
            assert wi.whisper_available(settings) is False
            target = Path(settings.media_root) / ".whisper" / "whisper"
            target.mkdir(parents=True)
            assert wi.whisper_available(settings) is True
            # Cagri ortami: PYTHONPATH hedefi icerir, mevcut PYTHONPATH
            # ezilmez.
            env = wi.subprocess_env(settings)
            assert env is not None
            assert str(Path(settings.media_root) / ".whisper") in env["PYTHONPATH"]
        finally:
            asyncio.run(engine.dispose())

    def test_available_via_interpreter_spec(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        sessionmaker, settings, engine = _env(tmp_path)
        try:
            monkeypatch.setattr(wi, "_spec_available", lambda: True)
            assert wi.whisper_available(settings) is True
            # Direct kurulumda ortam miras alinir (env yok).
            assert wi.subprocess_env(settings) is None
        finally:
            asyncio.run(engine.dispose())


class TestWhisperInstallApi:
    def test_status_endpoint_reports_missing(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi, "_spec_available", lambda: False)
        app = _make_app(tmp_path, worker_enabled=False, media_root=str(tmp_path))
        with TestClient(app) as client:
            body = client.get("/api/whisper").json()
        assert body["installed"] is False
        assert body["platform"]
        assert body["status"] is None

    def test_install_flow_succeeds(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi, "_spec_available", lambda: False)

        async def fake_run(cmd):
            # 'pip' basarili: hedef dizine paketi 'kurar'.
            target = tmp_path / "media" / ".whisper" / "whisper"
            target.mkdir(parents=True, exist_ok=True)
            return 0, "Successfully installed openai-whisper"

        monkeypatch.setattr(wi, "run_install", fake_run)
        app = _make_app(
            tmp_path, worker_enabled=False, media_root=str(tmp_path / "media")
        )
        with TestClient(app) as client:
            started = client.post("/api/whisper/install")
            assert started.status_code == 202, started.text
            assert started.json()["state"] == "running"

            # Arka plan gorevi hizla biter; durum 'succeeded' olur.
            installed = False
            final_state = None
            for _ in range(60):
                body = client.get("/api/whisper").json()
                final_state = (body.get("status") or {}).get("state")
                if body["installed"] and final_state == "succeeded":
                    installed = True
                    break
                time.sleep(0.05)
            assert installed, f"kurulum tamamlanmadi: {final_state}"

            # Kurulduktan sonra tekrar kurulum 400 verir.
            again = client.post("/api/whisper/install")
            assert again.status_code == 400

    def test_install_rejected_when_running(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi, "_spec_available", lambda: False)

        async def stuck_run(cmd):
            await asyncio.sleep(30)
            return 1, "gec"

        monkeypatch.setattr(wi, "run_install", stuck_run)
        app = _make_app(
            tmp_path, worker_enabled=False, media_root=str(tmp_path / "media")
        )
        with TestClient(app) as client:
            first = client.post("/api/whisper/install")
            assert first.status_code == 202
            # Ikinci istek ayni anda reddedilir.
            second = client.post("/api/whisper/install")
            assert second.status_code == 409

    def test_install_rejected_without_disk(self, tmp_path, monkeypatch):
        import app.services.whisper_install as wi

        monkeypatch.setattr(wi, "_spec_available", lambda: False)
        # Rota disk kontrolunu dogrudan import eder: rotanin bagini yamala.
        monkeypatch.setattr(
            "app.api.routes.whisper.disk_ok_for_install", lambda s: False
        )
        app = _make_app(
            tmp_path, worker_enabled=False, media_root=str(tmp_path / "media")
        )
        with TestClient(app) as client:
            response = client.post("/api/whisper/install")
            assert response.status_code == 503
            assert "disk" in response.json()["detail"].lower()


class TestTranscriberContract:
    def test_command_uses_interpreter_module_invocation(self, tmp_path):
        from app.services.media_transcript import WhisperTranscriber

        transcriber = WhisperTranscriber()
        cmd = transcriber.build_command(
            tmp_path / "v.mp4",
            tmp_path / "out",
            model="tiny",
            language="tr",
        )
        # python -m whisper: PATH'e bagimli degil, kurulum ortamiyla
        # ayni yorumlayici.
        assert cmd[:3] == [sys.executable, "-m", "whisper"]
        assert "--model" in cmd and "tiny" in cmd
        assert "--language" in cmd and "tr" in cmd
        assert "--output_format" in cmd and "srt" in cmd

    def test_missing_whisper_gives_actionable_error(self, tmp_path, monkeypatch):
        import app.services.media_transcript as mt

        monkeypatch.setattr(mt, "_spec_available", lambda: False)
        media = tmp_path / "v.mp4"
        media.write_bytes(b"x")
        transcriber = mt.WhisperTranscriber()

        async def scenario():
            try:
                await transcriber.transcribe(
                    media, tmp_path / "out", model="tiny", language="tr"
                )
                return None
            except mt.TranscriptError as exc:
                return str(exc)

        message = asyncio.run(scenario())
        assert message is not None
        assert "Indir ve Kur" in message
