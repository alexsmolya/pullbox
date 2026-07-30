"""Operator API for native direct-download artifact-host settings."""

from __future__ import annotations

from fastapi import APIRouter

from pullbox.api.deps import (  # noqa: TC001 - FastAPI resolves route annotations
    DbSession,
    InteractiveOperatorUser,
)
from pullbox.models.direct_acquisition import DirectArtifactHostKind  # noqa: TC001
from pullbox.schemas.direct_host import (
    DirectHostResponse,
    DirectHostTestResponse,
    DirectHostUpdateRequest,
)
from pullbox.services.direct_host_reachability import (
    DirectHostProbe,
    check_direct_host_reachability,
    probe_direct_host_endpoint,
)
from pullbox.services.direct_host_settings import (
    list_direct_host_settings,
    update_direct_host_setting,
)

router = APIRouter(
    prefix="/direct-hosts",
    tags=["direct-hosts"],
    include_in_schema=False,
)

direct_host_probe: DirectHostProbe = probe_direct_host_endpoint


@router.get("", response_model=list[DirectHostResponse])
async def list_host_settings(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> list[DirectHostResponse]:
    return [
        DirectHostResponse.model_validate(value)
        for value in await list_direct_host_settings(session)
    ]


@router.patch("/{host_kind}", response_model=DirectHostResponse)
async def update_host_setting(
    host_kind: DirectArtifactHostKind,
    body: DirectHostUpdateRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectHostResponse:
    value = await update_direct_host_setting(
        session,
        host_kind,
        enabled=body.enabled,
        preference=body.preference,
        credential_updates=body.credential_updates,
    )
    return DirectHostResponse.model_validate(value)


@router.post("/{host_kind}/test", response_model=DirectHostTestResponse)
async def test_host_reachability(
    host_kind: DirectArtifactHostKind,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectHostTestResponse:
    value = await check_direct_host_reachability(
        session,
        host_kind,
        probe=direct_host_probe,
    )
    return DirectHostTestResponse.model_validate(value)
