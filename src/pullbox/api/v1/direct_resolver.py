"""Operator API for the shared direct-download browser resolver."""

from __future__ import annotations

from typing import Never

from fastapi import APIRouter, HTTPException, Response, status

from pullbox.api.deps import (  # noqa: TC001 - FastAPI resolves annotations
    DbSession,
    InteractiveOperatorUser,
)
from pullbox.schemas.direct_resolver import (
    DirectResolverProfileRequest,
    DirectResolverResponse,
    DirectResolverTestResponse,
    DirectResolverUpdateRequest,
)
from pullbox.services.direct_resolver_service import (
    DirectResolverClientFactory,
    DirectResolverCreate,
    DirectResolverServiceError,
    DirectResolverUpdate,
    _default_client_factory,
    create_direct_resolver,
    delete_direct_resolver,
    get_direct_resolver,
    list_direct_resolvers,
    test_direct_resolver,
    update_direct_resolver,
    update_direct_resolver_profile,
)

router = APIRouter(
    prefix="/direct-resolver",
    tags=["direct-resolver"],
    include_in_schema=False,
)

direct_resolver_client_factory: DirectResolverClientFactory = _default_client_factory


def _raise_http_error(exc: DirectResolverServiceError) -> Never:
    if exc.code == "resolver_not_found":
        status_code = 404
    elif exc.code in {
        "resolver_endpoint_rejected",
        "resolver_unavailable",
        "resolver_timed_out",
    }:
        status_code = 502
    else:
        status_code = 422
    raise HTTPException(status_code=status_code, detail=exc.message) from exc


def _profile_update(body: DirectResolverProfileRequest) -> DirectResolverCreate:
    return DirectResolverCreate(
        name=body.name,
        resolver_kind=body.resolver_kind,
        priority=body.priority,
        endpoint=body.endpoint,
        enabled=body.enabled,
        allow_private_http=body.allow_private_http,
        timeout_seconds=body.timeout_seconds,
        max_concurrency=body.max_concurrency,
        authentication_headers=body.authentication_headers,
    )


@router.get("/profiles", response_model=list[DirectResolverResponse])
async def list_resolver_profiles(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> list[DirectResolverResponse]:
    return [
        DirectResolverResponse.model_validate(value)
        for value in await list_direct_resolvers(session)
    ]


@router.post(
    "/profiles",
    response_model=DirectResolverResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resolver_profile(
    body: DirectResolverProfileRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverResponse:
    try:
        value = await create_direct_resolver(
            session,
            _profile_update(body),
            client_factory=direct_resolver_client_factory,
        )
        return DirectResolverResponse.model_validate(value)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)


@router.patch("/profiles/{resolver_id}", response_model=DirectResolverResponse)
async def update_resolver_profile(
    resolver_id: int,
    body: DirectResolverProfileRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverResponse:
    try:
        value = await update_direct_resolver_profile(
            session,
            resolver_id,
            _profile_update(body),
            client_factory=direct_resolver_client_factory,
        )
        return DirectResolverResponse.model_validate(value)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)


@router.post("/profiles/{resolver_id}/test", response_model=DirectResolverTestResponse)
async def test_resolver_profile(
    resolver_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectResolverTestResponse:
    try:
        value = await test_direct_resolver(
            session,
            resolver_id=resolver_id,
            client_factory=direct_resolver_client_factory,
        )
        return DirectResolverTestResponse.model_validate(value)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)


@router.delete("/profiles/{resolver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_resolver_profile(
    resolver_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> Response:
    try:
        await delete_direct_resolver(session, resolver_id)
    except DirectResolverServiceError as exc:
        _raise_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
