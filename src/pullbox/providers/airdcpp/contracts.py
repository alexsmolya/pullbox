"""Strict required and additive-compatible AirDC++ wire contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Port = Annotated[StrictInt, Field(ge=0, le=65535)]
BoundedString = Annotated[StrictStr, Field(min_length=1, max_length=1000)]


class AirDcppWireModel(BaseModel):
    """Base policy: strict known fields while accepting additive server fields."""

    model_config = ConfigDict(extra="ignore", strict=True)


class AirDcppSystemInfo(AirDcppWireModel):
    api_version: NonNegativeInt
    api_feature_level: NonNegativeInt
    client_version: BoundedString
    platform: BoundedString
    path_separator: Annotated[StrictStr, Field(min_length=1, max_length=8)]


class AirDcppWebUser(AirDcppWireModel):
    username: Annotated[StrictStr, Field(min_length=1, max_length=255, repr=False)]
    permissions: Annotated[list[BoundedString], Field(max_length=100)]


class AirDcppAuthenticationInfo(AirDcppWireModel):
    session_id: PositiveInt
    auth_token: SecretStr = Field(repr=False)
    token_type: Annotated[StrictStr, Field(pattern=r"(?i)^bearer$", max_length=32)]
    system_info: AirDcppSystemInfo
    user: AirDcppWebUser
    wizard_pending: StrictBool


class AirDcppSession(AirDcppWireModel):
    id: PositiveInt
    user: AirDcppWebUser


class AirDcppHubConnectState(AirDcppWireModel):
    id: BoundedString
    str: Annotated[StrictStr, Field(max_length=500)]


class AirDcppHub(AirDcppWireModel):
    id: PositiveInt
    hub_url: SecretStr = Field(repr=False)
    connect_state: AirDcppHubConnectState

    @property
    def connected(self) -> bool:
        return self.connect_state.id == "connected"


class AirDcppConnectivityStatus(AirDcppWireModel):
    auto_detect: StrictBool
    enabled: StrictBool
    text: Annotated[StrictStr, Field(max_length=500)]
    bind_address: SecretStr = Field(repr=False)
    external_ip: SecretStr = Field(repr=False)


class AirDcppConnectivityInfo(AirDcppWireModel):
    status_v4: AirDcppConnectivityStatus
    status_v6: AirDcppConnectivityStatus
    tcp_port: Port
    tls_port: Port
    udp_port: Port


class AirDcppQueuePriority(AirDcppWireModel):
    id: Annotated[StrictInt, Field(ge=-1, le=6)]
    str: Annotated[StrictStr, Field(max_length=100)]
    auto: StrictBool


class AirDcppQueueSourceInfo(AirDcppWireModel):
    online: NonNegativeInt
    total: NonNegativeInt
    str: Annotated[StrictStr, Field(max_length=100)]

    @model_validator(mode="after")
    def validate_counts(self) -> AirDcppQueueSourceInfo:
        if self.online > self.total:
            raise ValueError("online source count cannot exceed total")
        return self


class AirDcppQueueStatus(AirDcppWireModel):
    id: BoundedString
    failed: StrictBool
    downloaded: StrictBool
    completed: StrictBool
    str: Annotated[StrictStr, Field(max_length=500)]


class AirDcppFileItemType(AirDcppWireModel):
    id: BoundedString


class AirDcppQueueBundle(AirDcppWireModel):
    id: PositiveInt
    name: BoundedString
    target: SecretStr = Field(repr=False)
    type: AirDcppFileItemType
    size: PositiveInt
    downloaded_bytes: NonNegativeInt
    priority: AirDcppQueuePriority
    time_added: NonNegativeInt
    time_finished: NonNegativeInt
    speed: NonNegativeInt
    seconds_left: NonNegativeInt
    sources: AirDcppQueueSourceInfo
    status: AirDcppQueueStatus

    @model_validator(mode="after")
    def validate_progress(self) -> AirDcppQueueBundle:
        if self.downloaded_bytes > self.size:
            raise ValueError("downloaded bytes cannot exceed bundle size")
        return self
