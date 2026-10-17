"""Pydantic schemas for the channel API.

Response schemas never carry OAuth tokens or any secret material.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    handle: str | None = Field(default=None, max_length=120)
    ribbon_color: str = "#3550c4"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("ribbon_color")
    @classmethod
    def _valid_hex(cls, value: str) -> str:
        if not HEX_COLOR.match(value):
            raise ValueError("ribbon_color #RRGGBB biçiminde olmalı")
        return value.lower()


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    handle: str | None = Field(default=None, max_length=120)
    ribbon_color: str | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("ribbon_color")
    @classmethod
    def _valid_hex(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not HEX_COLOR.match(value):
            raise ValueError("ribbon_color #RRGGBB biçiminde olmalı")
        return value.lower()


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    handle: str | None
    youtube_channel_id: str | None
    status: str
    ribbon_color: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    last_connected_at: datetime | None
    last_disconnected_at: datetime | None


class ChannelsOut(BaseModel):
    channels: list[ChannelOut]
    total: int
    connected: int


class MetadataTemplateIn(BaseModel):
    title_pattern: str | None = None
    description_pattern: str | None = None
    base_tags: list[str] | None = None
