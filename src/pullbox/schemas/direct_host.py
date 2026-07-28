"""API schemas for native direct-download artifact-host settings."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this at runtime

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.direct_acquisition import (  # noqa: TC001 - Pydantic resolves enums
    DirectArtifactHostKind,
    DirectHostAccountState,
)


class DirectHostUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    preference: int | None = Field(default=None, ge=0, le=1_000)
    credential_updates: dict[str, str | None] | None = Field(default=None, repr=False)


class DirectHostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    host_kind: DirectArtifactHostKind
    enabled: bool
    preference: int
    account_state: DirectHostAccountState
    credentials_configured: bool
    configured_credential_fields: tuple[str, ...]
    allowed_credential_fields: tuple[str, ...]
    redacted_identity: str | None
    quota_remaining: int | None
    quota_reset_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None
