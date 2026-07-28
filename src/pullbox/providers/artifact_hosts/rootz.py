"""Rootz short-link to signed-download resolution."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.contract import (
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.helpers import (
    contract_changed,
    parse_json_object,
    positive_int,
    safe_filename,
    validate_resolution_request,
)
from pullbox.providers.artifact_hosts.http import request_bounded, validate_artifact_url

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx

    from pullbox.providers.artifact_hosts.http import ArtifactUrlResolver

_SHORT_ID = re.compile(r"^[A-Za-z0-9_-]{2,100}$")
_PAGE_TOKEN = re.compile(r'"?pageToken"?\s*:\s*"([^"\\]{8,512})"')
_ROOTZ_DOMAINS = ("rootz.so",)
_ROOTZ_TRANSFER_DOMAINS = ("alcyone.so", "rootz.so")


class RootzAdapter:
    """Resolve Rootz's bounded public short-ID and UUID APIs."""

    host_kind = DirectArtifactHostKind.ROOTZ

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        resolver: ArtifactUrlResolver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._http_client = http_client
        self._resolver = resolver
        self._clock = clock or (lambda: datetime.now(UTC))

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
        short_id = _extract_short_id(source_url)
        page = await request_bounded(
            self._http_client,
            "GET",
            source_url,
            resolver=self._resolver,
            allowed_domains=_ROOTZ_DOMAINS,
            headers={"Accept": "text/html"},
        )
        if page.status_code != 200:
            raise contract_changed()
        page_token = _extract_page_token(page.text)
        short_response = await request_bounded(
            self._http_client,
            "GET",
            f"https://rootz.so/api/files/download-by-short?shortId={short_id}",
            resolver=self._resolver,
            allowed_domains=_ROOTZ_DOMAINS,
            headers={"Accept": "application/json", "X-Page-Token": page_token},
        )
        short_payload = parse_json_object(short_response)
        short_data = short_payload.get("data")
        if (
            short_response.status_code != 200
            or short_payload.get("success") is not True
            or not isinstance(short_data, dict)
            or short_data.get("status") != "active"
            or short_data.get("downloadAllowed") is False
        ):
            raise contract_changed()
        file_id = short_data.get("fileId")
        if not isinstance(file_id, str):
            raise contract_changed()
        try:
            UUID(file_id)
        except ValueError as exc:
            raise contract_changed() from exc

        download_response = await request_bounded(
            self._http_client,
            "GET",
            f"https://rootz.so/api/files/download/{file_id}",
            resolver=self._resolver,
            allowed_domains=_ROOTZ_DOMAINS,
            headers={"Accept": "application/json"},
        )
        payload = parse_json_object(download_response)
        data = payload.get("data")
        if download_response.status_code != 200 or payload.get("success") is not True:
            raise contract_changed()
        if not isinstance(data, dict) or not isinstance(data.get("url"), str):
            raise contract_changed()
        transfer_url = data["url"]
        await validate_artifact_url(
            transfer_url,
            allowed_domains=_ROOTZ_TRANSFER_DOMAINS,
            resolver=self._resolver,
        )
        size = positive_int(data.get("size")) or positive_int(short_data.get("size"))
        if size is None:
            raise contract_changed()
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=transfer_url,
            headers={},
            expected_size=size,
            expires_at=_expiration(data, self._clock()),
            filename_hint=(
                safe_filename(data.get("fileName")) or safe_filename(short_data.get("name"))
            ),
            range_supported=True,
        )


def _extract_short_id(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) != 2 or parts[0] != "d" or not _SHORT_ID.fullmatch(parts[1]):
        raise contract_changed()
    return parts[1]


def _extract_page_token(document: str) -> str:
    normalized = document
    for _ in range(3):
        normalized = normalized.replace('\\"', '"')
    match = _PAGE_TOKEN.search(normalized)
    if not match:
        raise contract_changed()
    return match.group(1)


def _expiration(data: Mapping[str, object], now: datetime) -> datetime | None:
    raw_expires_at = data.get("expiresAt")
    if isinstance(raw_expires_at, str) and raw_expires_at:
        try:
            parsed = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise contract_changed() from exc
        return parsed.astimezone(UTC)
    seconds = positive_int(data.get("expiresIn"), maximum=7 * 24 * 60 * 60)
    return now + timedelta(seconds=seconds) if seconds is not None else None
