"""Operator API for external direct-download provider registrations."""

from __future__ import annotations

from typing import Never

from fastapi import APIRouter, HTTPException, Response

from pullbox.api.deps import (  # noqa: TC001 - FastAPI resolves route annotations
    DbSession,
    InteractiveOperatorUser,
)
from pullbox.schemas.direct_provider import (
    DirectProviderRegisterRequest,
    DirectProviderResponse,
    DirectProviderTestResponse,
    DirectProviderUpdateRequest,
)
from pullbox.services.direct_provider_registration import (
    DirectProviderClientFactory,
    DirectProviderRegistrationError,
    DirectProviderRegistrationInput,
    _default_client_factory,
    disable_direct_provider,
    enable_direct_provider,
    get_direct_provider,
    list_direct_providers,
    register_direct_provider,
    remove_direct_provider,
    test_direct_provider,
    update_direct_provider,
)

router = APIRouter(
    prefix="/direct-providers",
    tags=["direct-providers"],
    include_in_schema=False,
)

direct_provider_client_factory: DirectProviderClientFactory = _default_client_factory


def _response(value: object) -> DirectProviderResponse:
    return DirectProviderResponse.model_validate(value)


def _raise_http_error(exc: DirectProviderRegistrationError) -> Never:
    if exc.code == "provider_not_found":
        status_code = 404
    elif exc.code in {
        "custom_provider_confirmation_required",
        "provider_endpoint_already_registered",
        "provider_identity_already_registered",
        "provider_not_usable",
        "provider_configuration_required",
    }:
        status_code = 409
    elif exc.code.startswith("provider_") and exc.code in {
        "provider_unavailable",
        "provider_timed_out",
        "provider_endpoint_rejected",
        "provider_authentication_failed",
        "provider_malformed_response",
    }:
        status_code = 502
    else:
        status_code = 422
    raise HTTPException(status_code=status_code, detail=exc.message) from exc


@router.get("", response_model=list[DirectProviderResponse])
async def list_provider_registrations(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> list[DirectProviderResponse]:
    return [_response(value) for value in await list_direct_providers(session)]


@router.get("/{provider_config_id}", response_model=DirectProviderResponse)
async def get_provider_registration(
    provider_config_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderResponse:
    try:
        return _response(await get_direct_provider(session, provider_config_id))
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.post("", response_model=DirectProviderResponse, status_code=201)
async def create_provider_registration(
    body: DirectProviderRegisterRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderResponse:
    try:
        value = await register_direct_provider(
            session,
            DirectProviderRegistrationInput(
                endpoint=body.endpoint,
                bearer_token=body.bearer_token,
                allow_private_http=body.allow_private_http,
                confirm_custom_provider=body.confirm_custom_provider,
                priority=body.priority,
            ),
            client_factory=direct_provider_client_factory,
        )
        return _response(value)
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.patch("/{provider_config_id}", response_model=DirectProviderResponse)
async def update_provider_registration(
    provider_config_id: int,
    body: DirectProviderUpdateRequest,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderResponse:
    try:
        value = await update_direct_provider(
            session,
            provider_config_id,
            priority=body.priority,
            bearer_token=body.bearer_token,
            public_configuration=body.public_configuration,
            secret_configuration=body.secret_configuration,
            resolver_enabled=body.resolver_enabled,
        )
        return _response(value)
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.post("/{provider_config_id}/test", response_model=DirectProviderTestResponse)
async def test_provider_registration(
    provider_config_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderTestResponse:
    try:
        value = await test_direct_provider(
            session,
            provider_config_id,
            client_factory=direct_provider_client_factory,
        )
        return DirectProviderTestResponse.model_validate(value)
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.post("/{provider_config_id}/enable", response_model=DirectProviderResponse)
async def enable_provider_registration(
    provider_config_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderResponse:
    try:
        return _response(
            await enable_direct_provider(
                session,
                provider_config_id,
                client_factory=direct_provider_client_factory,
            )
        )
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.post("/{provider_config_id}/disable", response_model=DirectProviderResponse)
async def disable_provider_registration(
    provider_config_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> DirectProviderResponse:
    try:
        return _response(await disable_direct_provider(session, provider_config_id))
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)


@router.delete("/{provider_config_id}", status_code=204)
async def delete_provider_registration(
    provider_config_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> Response:
    try:
        await remove_direct_provider(session, provider_config_id)
    except DirectProviderRegistrationError as exc:
        _raise_http_error(exc)
    return Response(status_code=204)
