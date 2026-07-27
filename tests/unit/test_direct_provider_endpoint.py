from __future__ import annotations

from collections.abc import Sequence  # noqa: TC003 - used by async fixture annotations

import pytest

from pullbox.providers.direct.endpoint import (
    ProviderEndpointError,
    validate_provider_endpoint,
)


async def _resolve_private(_host: str, _port: int) -> Sequence[str]:
    return ["172.20.0.8"]


async def _resolve_public(_host: str, _port: int) -> Sequence[str]:
    return ["8.8.8.8"]


async def _resolve_loopback(_host: str, _port: int) -> Sequence[str]:
    return ["127.0.0.1"]


async def _resolve_metadata(_host: str, _port: int) -> Sequence[str]:
    return ["169.254.169.254"]


async def _resolve_private_ipv6(_host: str, _port: int) -> Sequence[str]:
    return ["fd00::8"]


async def _resolve_mixed(_host: str, _port: int) -> Sequence[str]:
    return ["172.20.0.8", "8.8.8.8"]


async def test_private_http_requires_explicit_registration_acknowledgement() -> None:
    with pytest.raises(ProviderEndpointError, match="private HTTP"):
        await validate_provider_endpoint(
            "http://provider:8780",
            allow_private_http=False,
            resolver=_resolve_private,
        )

    endpoint = await validate_provider_endpoint(
        "http://provider:8780/",
        allow_private_http=True,
        resolver=_resolve_private,
    )

    assert endpoint.url == "http://provider:8780"
    assert endpoint.private_network is True
    assert endpoint.insecure_transport is True


async def test_localhost_http_can_be_explicitly_registered_for_native_installs() -> None:
    endpoint = await validate_provider_endpoint(
        "http://localhost:8780",
        allow_private_http=True,
        resolver=_resolve_loopback,
    )

    assert endpoint.private_network is True


async def test_private_ipv6_endpoint_is_normalized_with_url_brackets() -> None:
    endpoint = await validate_provider_endpoint(
        "http://[fd00::8]:8780",
        allow_private_http=True,
        resolver=_resolve_private_ipv6,
    )

    assert endpoint.url == "http://[fd00::8]:8780"
    assert endpoint.host == "fd00::8"


async def test_mixed_public_and_private_dns_answers_are_rejected() -> None:
    with pytest.raises(ProviderEndpointError, match="mixed network"):
        await validate_provider_endpoint(
            "https://provider.example",
            allow_private_http=False,
            resolver=_resolve_mixed,
        )


async def test_public_http_is_rejected_even_with_private_http_acknowledgement() -> None:
    with pytest.raises(ProviderEndpointError, match="HTTPS"):
        await validate_provider_endpoint(
            "http://provider.example",
            allow_private_http=True,
            resolver=_resolve_public,
        )


async def test_public_https_is_accepted() -> None:
    endpoint = await validate_provider_endpoint(
        "https://provider.example",
        allow_private_http=False,
        resolver=_resolve_public,
    )

    assert endpoint.url == "https://provider.example"
    assert endpoint.private_network is False
    assert endpoint.insecure_transport is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://provider.example",
        "https://user:pass@provider.example",
        "https://provider.example/path",
        "https://provider.example?token=secret",
        "https://provider.example/#fragment",
    ],
)
async def test_endpoint_rejects_unsafe_url_shapes(url: str) -> None:
    with pytest.raises(ProviderEndpointError):
        await validate_provider_endpoint(
            url,
            allow_private_http=False,
            resolver=_resolve_public,
        )


async def test_link_local_metadata_destinations_are_always_rejected() -> None:
    with pytest.raises(ProviderEndpointError, match="unsafe network"):
        await validate_provider_endpoint(
            "https://metadata.internal",
            allow_private_http=True,
            resolver=_resolve_metadata,
        )
