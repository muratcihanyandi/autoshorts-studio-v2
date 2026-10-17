"""Jobs API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: int
    job_type: str
    payload: dict[str, Any] | None
    status: str
    priority: int
    attempts: int
    max_attempts: int
    last_error: str | None
    worker_id: str | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobsOut(BaseModel):
    jobs: list[JobOut]
    total: int


class JobEnqueue(BaseModel):
    job_type: str = Field(min_length=1, max_length=48)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=9)
    max_attempts: int = Field(default=3, ge=1, le=10)
