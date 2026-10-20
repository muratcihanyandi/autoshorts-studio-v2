"""Runtime Whisper installation (platform-aware, UI-triggered).

The 'whisper' CLI is the openai-whisper PyPI package running on the
backend's own interpreter (`python -m whisper`), so installing it means
a pip install into this environment — triggered from the Settings
screen when the binary is missing:

- Windows dev machine: plain pip install into the venv (user-writable,
  `python -m whisper` resolves without PATH games).
- Linux / Raspberry Pi 5 container: the process runs as uid 1000 while
  system site-packages are root-owned, so the install targets a
  writable directory inside the mounted media tree
  (<MEDIA_ROOT>/.whisper) and every invocation passes that directory
  through PYTHONPATH. This also makes the install SURVIVE container
  recreation, because the media tree is a persistent volume.

Installations run as a background task; their state lives in app_meta
under 'whisper_install' so the UI polls honestly (running / succeeded /
failed with the pip output tail — never silent success).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import platform as platform_mod
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings

logger = logging.getLogger(__name__)

# Sabit surum: tekrarlanabilir kurulum (torch bagimliligi pip'in
# cozmesine birakilir; PyPI varsayilanlari her iki platformda da
# CPU tekerlekleridir).
WHISPER_PACKAGE = "openai-whisper==20231117"

# openai-whisper PyPI'da yalnizca kaynak paketi (sdist) olarak dagitilir
# ve setup.py'si pkg_resources import eder. Pip'in izole build ortamina
# indirdigi en yeni setuptools bu modulu kaldiriyor; kurulum bunun
# yuzunden dusuyor. --no-build-isolation, build'i bu yorumlayicinin
# kendi setuptools'unun (pkg_resources iceren surum) yurutmesini saglar.
BUILD_ISOLATION_OFF = "--no-build-isolation"

# torch 2026 tekerleri (aarch64 dahil) butun CUDA 13 yiginini
# bagimlilik olarak ceker: Pi'de kullanilmayan ~4 GB ve paylasilan medya
# diskine agir yuk. --no-deps + acik bagimlilik listesi kurulumu
# yalnizca CPU calisma zamani paketlerine indirir (~600 MB). Liste,
# whisper'in install_requires'i ile torch/numba/tiktoken'in import
# zincirini kapsar; yeni bir bagimlilik eklendiginde burada taze tut.
LEAN_DEPS = (
    "torch",
    "numpy",
    "numba",
    "llvmlite",
    "tiktoken",
    "tqdm",
    "more-itertools",
    "requests",
    "regex",
    "certifi",
    "charset_normalizer",
    "idna",
    "urllib3",
    "filelock",
    "typing-extensions",
    "jinja2",
    "MarkupSafe",
    "fsspec",
    "sympy",
    "networkx",
)

INSTALL_STATE_KEY = "whisper_install"
INSTALL_DISK_GB = 2.0
INSTALL_TIMEOUT_SECONDS = 3600.0
LOG_TAIL_CHARS = 2000


class WhisperInstallError(Exception):
    """Install planning failure with a user-facing Turkish message."""


def target_dir(settings: Settings) -> Path | None:
    """Linux hedefli kurulum dizini: kalici medya agacinda .whisper."""
    if not settings.media_root:
        return None
    return Path(settings.media_root) / ".whisper"


def _spec_available() -> bool:
    """Whisper bu yorumlayicida import edilebilir mi? (direct kurulum)"""
    try:
        return importlib.util.find_spec("whisper") is not None
    except Exception:  # noqa: BLE001 - bozuk kurulum = yok say
        return False


def whisper_available(settings: Settings) -> bool:
    """Kurulum sensin mi: venv'e direct kurulmus ya da hedef dizinde
    paket duruyor mu? (Arayuzdeki 'Indir ve Kur' bunun yoklugunda
    gorunur.)"""
    if _spec_available():
        return True
    target = target_dir(settings)
    return target is not None and (target / "whisper").is_dir()


def platform_info() -> dict:
    return {
        "platform": platform_mod.system(),
        "machine": platform_mod.machine(),
    }


def plan_install(settings: Settings) -> dict:
    """Platforma gore kurulum plani.

    Windows: venv icine direct kurulum (kullanici yazabilir).
    Linux (Pi konteyneri, uid 1000): sistem site-packages root'un
    oldugundan --target ile kalici medya agacina; cagrilar PYTHONPATH
    uzerinden cozulur. media_root yoksa direct denenir (hata olursa
    pip ciktisi kullaniciya gosterilir).
    """
    pkgs = [WHISPER_PACKAGE, *LEAN_DEPS]
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        BUILD_ISOLATION_OFF,
        "--no-deps",
    ]
    cmd = base + pkgs
    if platform_mod.system() == "Windows":
        return {
            "mode": "direct",
            "target": None,
            "cmd": cmd,
            "env": {},
        }
    target = target_dir(settings)
    if target is not None:
        target_cmd = base + ["--target", str(target), *pkgs]
        return {
            "mode": "target",
            "target": str(target),
            "cmd": target_cmd,
            "env": {"PYTHONPATH": str(target)},
        }
    return {"mode": "direct", "target": None, "cmd": cmd, "env": {}}


def subprocess_env(settings: Settings) -> dict | None:
    """Whisper cagrilari icin tam ortam (PYTHONPATH hedefli kurulumda).
    Direct kurulumda None: surec ortami miras alinir."""
    if _spec_available():
        return None
    target = target_dir(settings)
    if target is not None and (target / "whisper").is_dir():
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{target}{os.pathsep}{existing}" if existing else str(target)
        )
        return env
    return None


def disk_ok_for_install(settings: Settings) -> bool:
    """Torch tekerlekleri buyuktur: kurulum oncesi serbest disk sarti
    (medya agacinin diski, yoksa yorumlayici dizini)."""
    target = target_dir(settings)
    location = str(target.parent) if target is not None else str(
        Path(sys.executable).parent
    )
    try:
        free = shutil.disk_usage(location).free
    except OSError:
        return False
    return free >= INSTALL_DISK_GB * 1024**3


async def run_install(cmd: list[str]) -> tuple[int, str]:
    """pip surecini kos; (cikis kodu, cikti kuyrugu). Zaman asiminda
    surec oldurulur ve hata olarak doner."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(), INSTALL_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise WhisperInstallError(
            "Whisper kurulumu zaman asimina ugradi (pip cikti alinamadi)."
        ) from None
    tail = out.decode("utf-8", "replace").strip()[-LOG_TAIL_CHARS:]
    return proc.returncode or 0, tail


# --- durum takibi (app_meta) ---


async def read_state(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> dict | None:
    if sessionmaker is None:
        return None
    from app.models import AppMeta

    try:
        async with sessionmaker() as session:
            row = await session.get(AppMeta, INSTALL_STATE_KEY)
        if row is not None and isinstance(row.value, dict):
            return dict(row.value)
    except Exception:  # noqa: BLE001 - okuma hatasi durumu gizlemez
        return None
    return None


async def write_state(
    sessionmaker: async_sessionmaker[AsyncSession], state: dict
) -> None:
    from app.models import AppMeta

    async with sessionmaker() as session:
        row = await session.get(AppMeta, INSTALL_STATE_KEY)
        if row is None:
            session.add(AppMeta(key=INSTALL_STATE_KEY, value=state))
        else:
            row.value = state
        await session.commit()


def _audit(
    session: AsyncSession, event_type: str, detail: dict
) -> None:
    from app.services.channel_service import record_event

    record_event(session, None, event_type, detail)


async def install_whisper(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> dict:
    """Kurulumu basta isaretle, arka planda kosur ve durumu guncelle.

    Bu fonksiyon API ucu tarafindan asyncio.create_task ile arka plan
    gorevi olarak baslatilir; kendisi state'i 'running' yazar, pip'i
    kosar ve sonucu 'succeeded'/'failed' olarak kaydeder.
    """
    plan = plan_install(settings)
    info = platform_info()
    running_state = {
        "state": "running",
        "mode": plan["mode"],
        "target": plan["target"],
        "platform": info["platform"],
        "machine": info["machine"],
        "started_at": datetime.now(UTC).isoformat(),
    }
    await write_state(sessionmaker, running_state)
    async with sessionmaker() as session:
        _audit(
            session,
            "whisper.install_started",
            {"mode": plan["mode"], "platform": info["platform"]},
        )
        await session.commit()

    final: dict
    try:
        returncode, tail = await run_install(plan["cmd"])
    except WhisperInstallError as exc:
        final = {**running_state, "state": "failed", "error": str(exc)}
        await write_state(sessionmaker, final)
        await _audit_result(sessionmaker, "whisper.install_failed", str(exc))
        return final
    except Exception as exc:  # noqa: BLE001 - pip beklenmedik hata
        message = f"{type(exc).__name__}: {exc}"
        final = {**running_state, "state": "failed", "error": message}
        await write_state(sessionmaker, final)
        await _audit_result(sessionmaker, "whisper.install_failed", message)
        return final

    if returncode != 0 or not whisper_available(settings):
        message = (
            f"pip cikis kodu {returncode}; kurulum dogrulanamadi. "
            f"Cikti: {tail[-800:]}"
        )
        final = {
            **running_state,
            "state": "failed",
            "error": message,
            "log_tail": tail,
        }
        await write_state(sessionmaker, final)
        await _audit_result(sessionmaker, "whisper.install_failed", message)
        return final

    final = {
        **running_state,
        "state": "succeeded",
        "finished_at": datetime.now(UTC).isoformat(),
    }
    await write_state(sessionmaker, final)
    async with sessionmaker() as session:
        _audit(
            session,
            "whisper.installed",
            {"mode": plan["mode"], "platform": info["platform"]},
        )
        await session.commit()
    logger.info("whisper kurulumu tamamlandi (mode=%s)", plan["mode"])
    return final


async def _audit_result(
    sessionmaker: async_sessionmaker[AsyncSession], event: str, reason: str
) -> None:
    try:
        async with sessionmaker() as session:
            _audit(session, event, {"reason": reason[:500]})
            await session.commit()
    except Exception:  # noqa: BLE001 - denetim yazimi best-effort
        logger.exception("whisper kurulum denetim olayi yazilamadi")
