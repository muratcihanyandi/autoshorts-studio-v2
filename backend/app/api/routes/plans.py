"""Subscription plans catalog (madde 6): what each plan includes and
what the current session's account has. Payment flow is intentionally
out of scope — this is the example subscription surface."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.auth_service import PLAN_CATALOG

router = APIRouter(tags=["plans"])


@router.get("/plans")
async def plans(request: Request) -> dict:
    user = getattr(request.state, "auth_user", None)
    current: dict = {"plan": None, "plan_expires_at": None}
    if user is not None:
        current = {
            "plan": user.plan,
            "plan_expires_at": user.plan_expires_at,
        }
    return {"current": current, "plans": PLAN_CATALOG}
