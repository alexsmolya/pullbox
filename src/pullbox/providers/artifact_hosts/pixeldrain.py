"""PixelDrain public and API-key-backed artifact resolution."""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
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
    from collections.abc import Mapping

    import httpx

    from pullbox.providers.artifact_hosts.http import ArtifactUrlResolver

_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{2,128}$")
_CHALLENGE_ERRORS = frozenset(
    {
        "file_rate_limited_captcha_required",
        "ip_download_limited_captcha_required",
        "server_overload_captcha_required",
        "virus_detected_captcha_required",
    }
)
_QUOTA_ERRORS = frozenset(
    {
        "download_limit_exceeded",
        "max_concurrent_downloads",
        "transfer_limit_exceeded",
    }
)
_AUTH_ERRORS = frozenset({"authentication_failed", "authentication_required", "forbidden"})


class PixelDrainAdapter:
    """Resolve stable PixelDrain file metadata without probing file bytes."""

    host_kind = DirectArtifactHostKind.PIXELDRAIN

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
        file_id = _extract_file_id(source_url)
        headers = _authorization_headers(credentials.get("api_key"))
        response = await request_bounded(
            self._http_client,
            "GET",
            f"https://pixeldrain.com/api/file/{file_id}/info",
            resolver=self._resolver,
            allowed_domains=("pixeldrain.com", "pixeldrain.net"),
            headers={"Accept": "application/json", **headers},
        )
        payload = parse_json_object(response)
        if response.status_code >= 400 or payload.get("success") is not True:
            raise _pixeldrain_error(payload, response.status_code)
        availability = payload.get("availability")
        if isinstance(availability, str) and availability:
            raise _pixeldrain_error({"value": availability}, 403)
        if payload.get("can_download") is False:
            raise _pixeldrain_error({"value": "forbidden"}, 403)
        size = positive_int(payload.get("size"))
        if size is None:
            raise contract_changed()

        download_url = f"https://pixeldrain.com/api/file/{file_id}?download"
        await validate_artifact_url(
            download_url,
            allowed_domains=("pixeldrain.com", "pixeldrain.net"),
            resolver=self._resolver,
        )
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=download_url,
            headers=headers,
            expected_size=size,
            checksum=request.checksum,
            etag=request.etag,
            last_modified=request.last_modified,
            expires_at=request.expires_at,
            filename_hint=safe_filename(payload.get("name")),
            range_supported=True,
            allowed_domains=("pixeldrain.com", "pixeldrain.net"),
        )


def _extract_file_id(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    candidate: str | None = None
    if len(parts) >= 2 and parts[0] == "u":
        candidate = parts[1]
    elif len(parts) >= 3 and parts[:2] == ["api", "file"]:
        candidate = parts[2]
    if candidate is None or not _FILE_ID.fullmatch(candidate):
        raise contract_changed()
    return candidate


def _authorization_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    token = base64.b64encode(f":{api_key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _pixeldrain_error(
    payload: Mapping[str, object],
    status_code: int,
) -> ArtifactHostResolutionError:
    code_value = payload.get("value")
    code = code_value if isinstance(code_value, str) and code_value else "artifact_host_unavailable"
    if code in _CHALLENGE_ERRORS:
        failure_class = DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE
        retryable = False
        intervention = True
    elif code in _QUOTA_ERRORS:
        failure_class = DirectArtifactFailureClass.HOST_QUOTA
        retryable = False
        intervention = True
    elif code in _AUTH_ERRORS or status_code == 401:
        failure_class = DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED
        retryable = False
        intervention = True
    elif status_code >= 500 or status_code == 429 or code == "internal":
        failure_class = DirectArtifactFailureClass.TRANSIENT_HOST
        retryable = True
        intervention = False
    else:
        failure_class = DirectArtifactFailureClass.PERMANENT_MIRROR
        retryable = False
        intervention = True
    return ArtifactHostResolutionError(
        code=code,
        message="PixelDrain could not resolve this artifact.",
        failure_class=failure_class,
        retryable=retryable,
        intervention=intervention,
        sensitive_context=payload,
    )
