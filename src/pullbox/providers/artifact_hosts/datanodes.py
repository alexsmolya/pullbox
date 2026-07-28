"""DataNodes public page-flow adapter with visible challenge handling."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest, ResolvedTransfer
from pullbox.providers.artifact_hosts.helpers import (
    challenge_required,
    contract_changed,
    filename_from_url,
    validate_resolution_request,
)
from pullbox.providers.artifact_hosts.html import HostPageParser, parse_host_page
from pullbox.providers.artifact_hosts.http import request_bounded, validate_artifact_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx

    from pullbox.providers.artifact_hosts.http import ArtifactUrlResolver

_DATANODES_DOMAINS = ("datanodes.to",)
_CHALLENGE_MARKERS = (
    "cf-turnstile",
    "g-recaptcha",
    "recaptcha-token",
    "turnstile-response",
)


class DataNodesAdapter:
    """Attempt the bounded free form once and surface challenges explicitly."""

    host_kind = DirectArtifactHostKind.DATANODES

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
            allowed_domains=_DATANODES_DOMAINS,
            headers={"Accept": "text/html"},
        )
        document = page.text
        _reject_challenge(document)
        parsed = parse_host_page(document)
        transfer_url = _download_anchor(parsed, page.url)
        if transfer_url is None:
            form = parsed.forms.get("downloadForm")
            if form is None or form.method != "POST":
                raise contract_changed()
            post_url = urljoin(page.url, form.action or page.url)
            response = await request_bounded(
                self._http_client,
                "POST",
                post_url,
                resolver=self._resolver,
                allowed_domains=_DATANODES_DOMAINS,
                headers={"Accept": "text/html"},
                data={**form.fields, "method_free": "Free Download >>"},
            )
            _reject_challenge(response.text)
            transfer_url = _download_anchor(parse_host_page(response.text), response.url)
        if transfer_url is None:
            raise contract_changed()
        await validate_artifact_url(
            transfer_url,
            allowed_domains=_DATANODES_DOMAINS,
            resolver=self._resolver,
        )
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=transfer_url,
            expected_size=request.expected_size,
            checksum=request.checksum,
            etag=request.etag,
            last_modified=request.last_modified,
            expires_at=request.expires_at,
            filename_hint=filename_from_url(transfer_url),
            range_supported=False,
            allowed_domains=_DATANODES_DOMAINS,
        )


def _reject_challenge(document: str) -> None:
    lowered = document.lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise challenge_required()


def _download_anchor(parsed: HostPageParser, base_url: str) -> str | None:
    raw_url = parsed.anchors.get("downloadbtn") or parsed.anchors.get("downloadButton")
    return urljoin(base_url, raw_url) if raw_url else None
