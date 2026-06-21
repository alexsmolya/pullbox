"""Authentication request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pullbox.core.api_keys import (
    MAX_API_KEY_NAME_LENGTH,
    api_key_expiration_is_before_today,
    normalize_api_key_name,
)


class LoginRequest(BaseModel):
    """Request body for user login."""

    username: str = Field(..., min_length=1, max_length=100, description="Username")
    password: str = Field(..., min_length=1, description="Password")


class APIKeyCreate(BaseModel):
    """Request body for generating a new API key."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_API_KEY_NAME_LENGTH,
        description="Descriptive name for the API key",
    )
    expires_at: datetime | None = Field(None, description="Optional expiration timestamp")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_api_key_name(value)
        return value

    @field_validator("expires_at")
    @classmethod
    def reject_past_expiration_dates(cls, value: datetime | None) -> datetime | None:
        if value is not None and api_key_expiration_is_before_today(value):
            msg = "API key expiration date cannot be in the past."
            raise ValueError(msg)
        return value


class APIKeyResponse(BaseModel):
    """API key data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool
    created_at: datetime


class APIKeyCreatedResponse(BaseModel):
    """Response after creating a new API key. Includes the raw key (shown only once)."""

    key: str = Field(description="The API key value (only shown at creation time)")
    api_key: APIKeyResponse


class SetupRequest(BaseModel):
    """Request body for first-run admin setup."""

    username: str = Field(..., min_length=3, max_length=100, description="Admin username")
    password: str = Field(..., min_length=8, description="Admin password")


class SetupAccountCreatedResponse(BaseModel):
    """Response after creating the first account during setup."""

    message: str


class UserResponse(BaseModel):
    """Public user data returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool


class AccountUpdateRequest(BaseModel):
    """Request body for updating username and/or password."""

    current_password: str = Field(
        ..., min_length=1, description="Current password for verification"
    )
    new_username: str | None = Field(None, min_length=3, max_length=100, description="New username")
    new_password: str | None = Field(None, min_length=8, description="New password")
    confirm_password: str | None = Field(None, description="Must match new_password")


class AccountUpdateResponse(BaseModel):
    """Response after account update."""

    message: str
    username_changed: bool = False
    password_changed: bool = False


class LoginResponse(BaseModel):
    """Response after successful login."""

    user: UserResponse
    csrf_token: str


class PolicyRequirement(BaseModel):
    """A single password policy requirement."""

    id: str
    label: str
    type: str


class PasswordPolicyResponse(BaseModel):
    """Password policy rules returned by the API."""

    min_length: int
    max_length: int
    max_bytes: int
    requirements: list[PolicyRequirement]
