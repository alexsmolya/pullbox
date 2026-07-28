"""TeraBox user-session resolution without a hosted credential broker."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest, ResolvedTransfer
from pullbox.providers.artifact_hosts.helpers import (
    auth_required,
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

_TERABOX_DOMAINS = (
    "1024terabox.com",
    "1024tera.com",
    "4funbox.com",
    "dubox.com",
    "mirrobox.com",
    "momerybox.com",
    "terabox.com",
    "terabox.app",
    "teraboxapp.com",
    "teraboxlink.com",
    "terasharefile.com",
)
_TERABOX_TRANSFER_DOMAINS = (
    "baidupcs.com",
    "terabox.com",
    "terabox.app",
    "teraboxapp.com",
    "teraboxcdn.com",
)
_MAX_TOKEN_SCRIPT_LENGTH = 4096
_JS_TOKEN_PATTERNS = (
    re.compile(r"\bjsToken\s*=\s*['\"]([^'\"]{4,2048})['\"]"),
    re.compile(r"['\"]jsToken['\"]\s*:\s*['\"]([^'\"]{4,2048})['\"]"),
)
_ENCODED_TOKEN_PATTERN = re.compile(
    r"\bfn\(\s*(['\"])([^'\"]{4,2048})\1\s*\)",
)
_AUTH_ERRNOS = frozenset({-6, -9, 400141, 4000020})


class TeraBoxAdapter:
    """Resolve a single shared file using a user-owned encrypted session cookie."""

    host_kind = DirectArtifactHostKind.TERABOX

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
        session = credentials.get("cookie") or credentials.get("session_token")
        if not session:
            raise auth_required()
        headers = {"Cookie": f"ndus={session}"}
        page = await request_bounded(
            self._http_client,
            "GET",
            source_url,
            resolver=self._resolver,
            allowed_domains=_TERABOX_DOMAINS,
            headers={"Accept": "text/html", **headers},
        )
        if page.status_code in {401, 403}:
            raise auth_required()
        if page.status_code != 200:
            raise contract_changed()
        js_token = _extract_js_token(page.text)
        short_url = _extract_short_url(source_url)
        api_url = (
            "https://www.terabox.com/share/list"
            f"?app_id=250528&web=1&channel=dubox&clienttype=0"
            f"&jsToken={quote(js_token, safe='')}&shorturl={quote(short_url, safe='')}"
            "&root=1&num=100&page=1&order=asc&by=name"
        )
        response = await request_bounded(
            self._http_client,
            "GET",
            api_url,
            resolver=self._resolver,
            allowed_domains=_TERABOX_DOMAINS,
            headers={"Accept": "application/json", **headers},
        )
        payload = parse_json_object(response)
        errno = payload.get("errno")
        if response.status_code in {401, 403} or errno in _AUTH_ERRNOS:
            raise auth_required()
        if response.status_code != 200 or errno != 0:
            raise contract_changed()
        raw_items = payload.get("list")
        if not isinstance(raw_items, list):
            raise contract_changed()
        items = [
            item for item in raw_items if isinstance(item, dict) and item.get("isdir") in {0, "0"}
        ]
        if len(items) != 1:
            raise contract_changed()
        item = items[0]
        transfer_url = item.get("dlink")
        if not isinstance(transfer_url, str):
            # TeraBox returns public metadata with errno=0 for expired sessions,
            # but withholds the signed download link until the user reauthenticates.
            raise auth_required()
        await validate_artifact_url(
            transfer_url,
            allowed_domains=_TERABOX_TRANSFER_DOMAINS,
            resolver=self._resolver,
        )
        size = positive_int(item.get("size"))
        if size is None:
            raise contract_changed()
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=transfer_url,
            headers=headers,
            expected_size=size,
            filename_hint=safe_filename(item.get("server_filename")),
            range_supported=False,
            allowed_domains=_TERABOX_TRANSFER_DOMAINS,
        )


def _extract_short_url(url: str) -> str:
    path = urlsplit(url).path
    marker = "/s/"
    if marker not in path:
        raise contract_changed()
    value = path.split(marker, 1)[1].split("/", 1)[0]
    if value.startswith("1"):
        value = value[1:]
    if not value or len(value) > 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise contract_changed()
    return value


def _extract_js_token(document: str) -> str:
    for pattern in _JS_TOKEN_PATTERNS:
        match = pattern.search(document)
        if match:
            return match.group(1)
    marker = document.find("jsToken")
    if marker >= 0:
        start = document.rfind("<script", 0, marker)
        end = document.find("</script>", marker)
        if start >= 0 and end >= 0 and end - start <= _MAX_TOKEN_SCRIPT_LENGTH:
            decoded = unquote(document[start:end])
            match = _ENCODED_TOKEN_PATTERN.search(decoded)
            if match:
                return match.group(2)
    raise contract_changed()
