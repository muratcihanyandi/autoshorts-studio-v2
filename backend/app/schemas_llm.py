"""LLM provider API schemas.

API keys are write-only: responses carry configured + a masked hint
(last 4 characters), never the value.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    google = "google"


class ApiKeyView(BaseModel):
    configured: bool
    hint: str


class LlmProviderOut(BaseModel):
    id: int
    name: str
    provider_type: ProviderType
    api_base: str
    model_id: str
    api_key: ApiKeyView  # secret-scan-ok: masked view, never carries the value
    enabled: bool
    priority: int
    timeout_seconds: int
    max_retries: int

    model_config = {"from_attributes": True}


class LlmProvidersOut(BaseModel):
    providers: list[LlmProviderOut]
    total: int
    enabled: int


class LlmProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_type: ProviderType
    api_base: str = Field(min_length=1, max_length=255)
    model_id: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    priority: int = Field(default=1, ge=1, le=3)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=3)


class LlmProviderUpdate(BaseModel):
    """PATCH semantics: None = untouched; api_key only changes when given."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    provider_type: ProviderType | None = None
    api_base: str | None = Field(default=None, min_length=1, max_length=255)
    model_id: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=1, max_length=512)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=3)


class LlmTestResult(BaseModel):
    provider_id: int
    status: str
    latency_ms: int
    detail: str


class LlmRequestLogOut(BaseModel):
    id: int
    request_id: str
    provider_name: str
    status: str
    latency_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LlmRequestLogsOut(BaseModel):
    logs: list[LlmRequestLogOut]
    total: int
