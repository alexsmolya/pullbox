"""Adversarial network and dispatch tests for artifact-host resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.http import request_bounded, validate_artifact_url
from pullbox.providers.artifact_hosts.mediafire import MediaFireAdapter
from pullbox.providers.artifact_hosts.resolver import ArtifactHostResolver

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


async def _public(_host: str, _port: int) -> Sequence[str]:
    return ["8.8.8.8"]


async def _private(_host: str, _port: int) -> Sequence[str]:
    return ["169.254.169.254"]


async def _mixed(_host: str, _port: int) -> Sequence[str]:
    return ["8.8.8.8", "127.0.0.1"]


@pytest.mark.parametrize("resolver", [_private, _mixed])
async def test_artifact_url_rejects_private_or_mixed_dns(
    resolver: object,
) -> None:
    with pytest.raises(ArtifactHostResolutionError) as raised:
        await validate_artifact_url(
            "https://files.example.test/fixture.cbz",
            resolver=resolver,  # type: ignore[arg-type]
        )

    assert raised.value.code == "unsafe_artifact_url"
    assert raised.value.failure_class is DirectArtifactFailureClass.SAFETY


async def test_redirect_target_is_revalidated_before_the_second_request() -> None:
    seen_hosts: list[str] = []

    async def resolver(host: str, _port: int) -> Sequence[str]:
        return ["127.0.0.1"] if host == "internal.example.test" else ["8.8.8.8"]

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.headers["Host"])
        return httpx.Response(302, headers={"Location": "https://internal.example.test/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await request_bounded(
                client,
                "GET",
                "https://files.example.test/fixture.cbz",
                resolver=resolver,
                allowed_domains=None,
            )

    assert seen_hosts == ["files.example.test"]
    assert raised.value.code == "unsafe_artifact_url"


async def test_metadata_response_limit_stops_unbounded_adapter_reads() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 33))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await request_bounded(
                client,
                "GET",
                "https://files.example.test/metadata",
                resolver=_public,
                allowed_domains=None,
                max_response_bytes=32,
            )

    assert raised.value.code == "artifact_host_response_too_large"
    assert raised.value.failure_class is DirectArtifactFailureClass.SAFETY


async def test_mediafire_cannot_redirect_transfer_to_an_unrelated_domain() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            text=(
                '<a id="downloadButton" '
                'href="https://169.254.169.254/latest/meta-data">Download</a>'
            ),
        )
    )
    request = HostResolutionRequest(
        artifact_identity="fixture",
        host_kind=DirectArtifactHostKind.MEDIAFIRE,
        share_url="https://mediafire.com/file/fixture/file",
        final_url=None,
    )

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await MediaFireAdapter(client, resolver=_public).resolve(request, credentials={})

    assert raised.value.code == "unsafe_artifact_url"


class _StubAdapter:
    host_kind = DirectArtifactHostKind.PIXELDRAIN

    def __init__(self) -> None:
        self.calls = 0

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Mapping[str, str],
    ) -> ResolvedTransfer:
        self.calls += 1
        assert credentials == {"api_key": "secret"}
        return ResolvedTransfer(
            host_kind=request.host_kind,
            url="https://pixeldrain.com/api/file/fixture",
        )


async def test_closed_resolver_dispatches_only_to_the_matching_adapter() -> None:
    adapter = _StubAdapter()
    resolver = ArtifactHostResolver((adapter,))
    request = HostResolutionRequest(
        artifact_identity="fixture",
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        share_url="https://pixeldrain.com/u/fixture",
        final_url=None,
    )

    transfer = await resolver.resolve(request, credentials={"api_key": "secret"})

    assert transfer.host_kind is DirectArtifactHostKind.PIXELDRAIN
    assert adapter.calls == 1


async def test_closed_resolver_rejects_unregistered_or_duplicate_adapters() -> None:
    adapter = _StubAdapter()
    with pytest.raises(ValueError, match="duplicate"):
        ArtifactHostResolver((adapter, adapter))

    resolver = ArtifactHostResolver((adapter,))
    request = HostResolutionRequest(
        artifact_identity="fixture",
        host_kind=DirectArtifactHostKind.MEDIAFIRE,
        share_url="https://mediafire.com/file/fixture/file",
        final_url=None,
    )
    with pytest.raises(ArtifactHostResolutionError) as raised:
        await resolver.resolve(request, credentials={})

    assert raised.value.code == "unsupported_artifact_host"
