"""Operator API schemas for the shared browser challenge resolver."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this at runtime

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.direct_acquisition import (  # noqa: TC001 - Pydantic runtime model
    DirectResolverKind,
    DirectResolverState,
)


class DirectResolverUpdateRequest(BaseModel):
    endpoint: str = Field(max_length=1_000)
    enabled: bool
    allow_private_http: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=60)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    authentication_headers: dict[str, str | None] | None = Field(default=None, repr=False)


class DirectResolverProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    resolver_kind: DirectResolverKind
    priority: int = Field(ge=1, le=1000)
    endpoint: str = Field(max_length=1_000)
    enabled: bool
    allow_private_http: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=60)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    authentication_headers: dict[str, str | None] | None = Field(default=None, repr=False)


class DirectResolverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    resolver_kind: DirectResolverKind
    priority: int
    endpoint: str
    enabled: bool
    state: DirectResolverState
    allow_private_http: bool
    timeout_seconds: int
    max_concurrency: int
    auth_headers_configured: bool
    auth_header_names: tuple[str, ...]
    last_health_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None


class DirectResolverTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    usable: bool
    state: DirectResolverState
    message: str
    checked_at: datetime
