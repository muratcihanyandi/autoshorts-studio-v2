"""Studio auth API: first-run signup, login, logout, session status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services.auth_service import (
    SESSION_COOKIE,
    AuthError,
    AuthService,
    authenticate,
    cookie_settings,
    verify_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    configured: bool
    authenticated: bool
    username: str | None = None
    # İlk hesap oluşturulana kadar kayıt açıktır; sonrasında kapanır.
    signup_open: bool = False


def _service(request: Request) -> AuthService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; giriş kapalı.",
        )
    return AuthService(sessionmaker, request.app.state.settings)


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        value=token,
        **cookie_settings(request.app.state.settings),
    )


@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request) -> AuthStatus:
    config = getattr(request.app.state, "auth_config", None)
    username = verify_session(
        config or {}, request.cookies.get(SESSION_COOKIE)
    )
    return AuthStatus(
        configured=config is not None,
        authenticated=username is not None,
        username=username,
        signup_open=config is None,
    )


async def _create_first_account(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    """İlk hesap: yalnızca henüz kullanıcı yokken çalışır."""
    service = _service(request)
    try:
        config = await service.setup(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    request.app.state.auth_config = config
    _set_cookie(response, request, service.token_for(config))
    return AuthStatus(
        configured=True,
        authenticated=True,
        username=str(config["username"]),
        signup_open=False,
    )


@router.post("/signup", response_model=AuthStatus, status_code=201)
async def signup(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    """İlk stüdyo hesabını oluştur (kayıt dönemi)."""
    return await _create_first_account(request, response, body)


@router.post("/setup", response_model=AuthStatus, status_code=201)
async def setup(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    """Geriye dönük uyumluluk: eski istemciler için /signup ile aynı."""
    return await _create_first_account(request, response, body)


@router.post("/login", response_model=AuthStatus)
async def login(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    config = getattr(request.app.state, "auth_config", None)
    if config is None:
        # Kurulum başka bir istekte tamamlanmış olabilir; tazele.
        config = await _service(request).get_config()
        request.app.state.auth_config = config
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Yönetici girişi henüz kurulmamış.",
        )
    if not authenticate(config, body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı.",
        )
    _set_cookie(response, request, AuthService.token_for(config))
    return AuthStatus(
        configured=True,
        authenticated=True,
        username=str(config["username"]),
        signup_open=False,
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response
