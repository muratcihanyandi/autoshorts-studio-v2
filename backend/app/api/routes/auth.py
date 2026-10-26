"""Studio auth API: first-run signup, login, logout, session status and
the account system (madde 6): profile, password change, user management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services.auth_service import (
    SESSION_COOKIE,
    AuthError,
    AuthService,
    SessionUser,
    cookie_settings,
    verify_user_session,
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


class MeOut(BaseModel):
    username: str
    role: str
    plan: str
    plan_expires_at: str | None = None
    is_active: bool


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: str = Field(pattern="^(admin|operator)$")
    plan: str = Field(pattern="^(free|pro)$")


class UserPatchIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|operator)$")
    plan: str | None = Field(default=None, pattern="^(free|pro)$")
    is_active: bool | None = None


def _service(request: Request) -> AuthService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; giriş kapalı.",
        )
    return AuthService(sessionmaker, request.app.state.settings)


def _current_user(request: Request) -> SessionUser:
    """Middleware'in koyduğu oturum kullanıcısı; yoksa 401."""
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum gerekli.",
        )
    return user


def _require_admin(request: Request) -> SessionUser:
    user = _current_user(request)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetici yetkisi gerekir.",
        )
    return user


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        value=token,
        **cookie_settings(request.app.state.settings),
    )


def _me_out(user: SessionUser) -> MeOut:
    return MeOut(
        username=user.username,
        role=user.role,
        plan=user.effective_plan,
        plan_expires_at=user.plan_expires_at,
        is_active=user.is_active,
    )


@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request) -> AuthStatus:
    config = getattr(request.app.state, "auth_config", None)
    user = None
    if config is not None:
        user = await verify_user_session(
            getattr(request.app.state, "sessionmaker", None),
            config,
            request.cookies.get(SESSION_COOKIE),
        )
    return AuthStatus(
        configured=config is not None,
        authenticated=user is not None,
        username=user.username if user else None,
        signup_open=True,
    )


@router.post("/signup", response_model=AuthStatus, status_code=201)
async def signup(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    """Kullanıcı kaydı: Sistemde hiç hesap yoksa ilk hesap yönetici olarak
    kurulur; sistem kuruluysa yeni operatör (ücretsiz plan) hesabı açılır."""
    service = _service(request)
    config = getattr(request.app.state, "auth_config", None)
    if config is None:
        config = await service.get_config()
        request.app.state.auth_config = config

    if config is None:
        try:
            config, user = await service.setup(body.username, body.password)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        request.app.state.auth_config = config
    else:
        try:
            user = await service.create_user(
                body.username, body.password, role="operator", plan="free"
            )
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    _set_cookie(response, request, AuthService.user_token_for(config, user))
    return AuthStatus(
        configured=True,
        authenticated=True,
        username=user.username,
        signup_open=True,
    )


@router.post("/setup", response_model=AuthStatus, status_code=201)
async def setup(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    """Geriye dönük uyumluluk: eski istemciler için /signup ile aynı."""
    return await signup(request, response, body)


@router.post("/login", response_model=AuthStatus)
async def login(
    request: Request, response: Response, body: Credentials
) -> AuthStatus:
    service = _service(request)
    config = getattr(request.app.state, "auth_config", None)
    if config is None:
        # Kurulum başka bir istekte tamamlanmış olabilir; tazele.
        config = await service.get_config()
        request.app.state.auth_config = config
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Yönetici girişi henüz kurulmamış.",
        )
    try:
        user = await service.get_user_by_credentials(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    _set_cookie(response, request, AuthService.user_token_for(config, user))
    return AuthStatus(
        configured=True,
        authenticated=True,
        username=user.username,
        signup_open=True,
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


# --- hesap sistemi (madde 6) ------------------------------------------------


@router.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    return _me_out(_current_user(request))


@router.post("/password")
async def change_password(
    request: Request, response: Response, body: PasswordChangeIn
) -> dict:
    """Şifreyi değiştir; token_version arttığı için eski çerez düşer,
    yeni çerez aynı yanıtta verilir (kullanıcı düşürülmez)."""
    user = _current_user(request)
    service = _service(request)
    try:
        updated = await service.change_password(
            user.id, body.current_password, body.new_password
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    config = getattr(request.app.state, "auth_config", None)
    if config is not None:
        _set_cookie(response, request, AuthService.user_token_for(config, updated))
    return {"ok": True}


@router.get("/users")
async def list_users(request: Request) -> dict:
    _require_admin(request)
    users = await _service(request).list_users()
    return {"users": [_user_out(u) for u in users]}


@router.post("/users", status_code=201)
async def create_user(request: Request, body: UserCreateIn) -> dict:
    _require_admin(request)
    try:
        user = await _service(request).create_user(
            body.username, body.password, body.role, body.plan
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"user": _user_out(user)}


@router.patch("/users/{user_id}")
async def patch_user(request: Request, user_id: int, body: UserPatchIn) -> dict:
    _require_admin(request)
    try:
        user = await _service(request).patch_user(
            user_id,
            role=body.role,
            plan=body.plan,
            is_active=body.is_active,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"user": _user_out(user)}


def _user_out(user: SessionUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "plan": user.plan,
        "plan_expires_at": user.plan_expires_at,
        "is_active": user.is_active,
    }
