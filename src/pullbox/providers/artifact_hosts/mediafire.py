"""MediaFire anonymous public-share resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest, ResolvedTransfer
from pullbox.providers.artifact_hosts.helpers import (
    contract_changed,
    filename_from_url,
    validate_resolution_request,
)
from pullbox.providers.artifact_hosts.html import parse_host_page
from pullbox.providers.artifact_hosts.http import request_bounded, validate_artifact_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx

    from pullbox.providers.artifact_hosts.http import ArtifactUrlResolver

_MEDIAFIRE_DOMAINS = ("mediafire.com",)


class MediaFireAdapter:
    """Extract the one bounded public download anchor from a MediaFire share."""

    host_kind = DirectArtifactHostKind.MEDIAFIRE

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        resolver: ArtifactUrlResolver | None = None,
    ) -> None:
        self._http_client = http_client
        self._resolver = resolver

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Mapping[str, str],
    ) -> ResolvedTransfer:
        source_url = validate_resolution_request(
            request,
            expected_kind=self.host_kind,
            credentials=credentials,
        )
        page = await request_bounded(
            self._http_client,
            "GET",
            source_url,
            resolver=self._resolver,
            allowed_domains=_MEDIAFIRE_DOMAINS,
            headers={"Accept": "text/html"},
        )
        if page.status_code != 200:
            raise contract_changed()
        parsed = parse_host_page(page.text)
        raw_url = parsed.anchors.get("downloadButton") or parsed.anchors.get("download_link")
        if not raw_url:
            raise contract_changed()
        transfer_url = urljoin(source_url, raw_url)
        await validate_artifact_url(
            transfer_url,
            allowed_domains=_MEDIAFIRE_DOMAINS,
            resolver=self._resolver,
        )
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=transfer_url,
            expected_size=request.expected_size,
            etag=request.etag,
            last_modified=request.last_modified,
            expires_at=request.expires_at,
            filename_hint=filename_from_url(transfer_url),
            range_supported=False,
            allowed_domains=_MEDIAFIRE_DOMAINS,
        )
