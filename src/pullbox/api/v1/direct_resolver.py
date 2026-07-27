"""Operator API for the shared direct-download browser resolver."""

from __future__ import annotations

from typing import Never

from fastapi import APIRouter, HTTPException

from pullbox.api.deps import (  # noqa: TC001 - FastAPI resolves annotations
    DbSession,
    InteractiveOperatorUser,
)
from pullbox.schemas.direct_resolver import (
    DirectResolverResponse,
    DirectResolverTestResponse,
    DirectResolverUpdateRequest,
)
from pullbox.services.direct_resolver_service import (
    DirectResolverClientFactory,
    DirectResolverServiceError,
    DirectResolverUpdate,
    _default_client_factory,
    get_direct_resolver,
    test_direct_resolver,
    update_direct_resolver,
)

router = APIRouter(
    prefix="/direct-resolver",
    tags=["direct-resolver"],
    include_in_schema=False,
)

direct_resolver_client_factory: DirectResolverClientFactory = _default_client_factory


def _raise_http_error(exc: DirectResolverServiceError) -> Never:
    status_code = (
        502
        if exc.code.startswith("resolver_")
        and exc.code
        in {
            "resolver_endpoint_rejected",
            "resolver_unavailable",
            "resolver_timed_out",
        }
        else 422
    )
    raise HTTPException(status_code=status_code, detail=exc.message) from exc


@router.get("", response_model=DirectResolverResponse)
async def get_resolver_configuration(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverResponse:
    return DirectResolverResponse.model_validate(await get_direct_resolver(session))


@router.patch("", response_model=DirectResolverResponse)
async def update_resolver_configuration(
    body: DirectResolverUpdateRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverResponse:
    try:
        value = await update_direct_resolver(
            session,
            DirectResolverUpdate(
                endpoint=body.endpoint,
                enabled=body.enabled,
                allow_private_http=body.allow_private_http,
                timeout_seconds=body.timeout_seconds,
                max_concurrency=body.max_concurrency,
                authentication_headers=body.authentication_headers,
            ),
            client_factory=direct_resolver_client_factory,
        )
        return DirectResolverResponse.model_validate(value)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)


@router.post("/test", response_model=DirectResolverTestResponse)
async def test_resolver_configuration(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverTestResponse:
    try:
        value = await test_direct_resolver(
            session,
            client_factory=direct_resolver_client_factory,
        )
        return DirectResolverTestResponse.model_validate(value)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)
