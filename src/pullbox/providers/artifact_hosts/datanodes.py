"""DataNodes registered-account and Premium download resolution."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest, ResolvedTransfer
from pullbox.providers.artifact_hosts.helpers import (
    auth_required,
    challenge_required,
    contract_changed,
    filename_from_url,
    validate_resolution_request,
)
from pullbox.providers.artifact_hosts.html import HostPageParser, ParsedForm, parse_host_page
from pullbox.providers.artifact_hosts.http import (
    BoundedArtifactResponse,
    cookie_header_for_url,
    request_bounded,
    validate_artifact_url,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from pullbox.providers.artifact_hosts.http import ArtifactUrlResolver
    from pullbox.providers.direct.resolver import DirectResolverResult

_DATANODES_DOMAINS = ("datanodes.to",)
_DATANODES_TRANSFER_DOMAINS = (*_DATANODES_DOMAINS, "dlproxy.uk")
_LOGIN_URL = "https://datanodes.to/login.html"
_DATANODES_REFERER = "https://datanodes.to/users"
_CHALLENGE_CLASSES = frozenset(
    {
        "cf-turnstile",
        "g-recaptcha",
        "h-captcha",
    }
)
_CHALLENGE_FORM_IDS = frozenset({"challenge-form"})
_CHALLENGE_FIELDS = frozenset(
    {
        "cf-turnstile-response",
        "g-recaptcha-response",
        "h-captcha-response",
        "recaptcha-token",
        "turnstile-response",
    }
)
_WAIT_PATTERNS = (
    re.compile(r"\bcountdown=[\"'](\d{1,3})[\"']", re.IGNORECASE),
    re.compile(r"\bcountdown\s*=\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bid=[\"']countdown[\"'][^>]*>\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bdata-wait=[\"'](\d{1,3})[\"']", re.IGNORECASE),
)
_RAND_PATTERN = re.compile(r"\brand=[\"']([^\"']{1,512})[\"']", re.IGNORECASE)
_INVALID_LOGIN_PATTERN = re.compile(
    r"\b(?:incorrect|invalid)\s+(?:login|username)(?:\s+or\s+password)?\b",
    re.IGNORECASE,
)
_FILE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MAX_WAIT_SECONDS = 300
_MAX_DOWNLOAD_FORM_SUBMISSIONS = 2
_MAX_LOGIN_HTML_BYTES = 2 * 1024 * 1024
_MAX_COMPONENT_VALUE_LENGTH = 4_000


@dataclass(frozen=True, slots=True)
class _PremiumDownloadComponent:
    fields: Mapping[str, str]


class _DataNodesComponentParser(HTMLParser):
    """Extract the one bounded Vue component that owns Premium downloads."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.download_components: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "download-countdown":
            return
        self.download_components.append({name.casefold(): value or "" for name, value in attrs})


class DataNodesAdapter:
    """Resolve public shares through a user-owned registered account."""

    host_kind = DirectArtifactHostKind.DATANODES

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        resolver: ArtifactUrlResolver | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        login_solver: Callable[[str], Awaitable[DirectResolverResult]] | None = None,
    ) -> None:
        self._http_client = http_client
        self._resolver = resolver
        self._sleep = sleep
        self._login_solver = login_solver

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
        username = credentials.get("username", "").strip()
        password = credentials.get("password", "")
        if not username or not password:
            raise auth_required()

        cookies = httpx.Cookies()
        user_agent = await self._authenticate(
            username=username,
            password=password,
            cookies=cookies,
        )
        page = await request_bounded(
            self._http_client,
            "GET",
            source_url,
            resolver=self._resolver,
            allowed_domains=_DATANODES_DOMAINS,
            headers=_request_headers("text/html", user_agent=user_agent),
            cookies=cookies,
        )
        parsed = _validated_page(page)
        if _login_form(parsed) is not None:
            raise auth_required()

        transfer_url = _download_anchor(parsed, page.url)
        if transfer_url is None:
            transfer_url = await self._resolve_registered_download(
                page,
                source_url=source_url,
                cookies=cookies,
                user_agent=user_agent,
            )
        await validate_artifact_url(
            transfer_url,
            allowed_domains=_DATANODES_TRANSFER_DOMAINS,
            resolver=self._resolver,
        )
        transfer_headers = {"Referer": source_url}
        if user_agent:
            transfer_headers["User-Agent"] = user_agent
        cookie_header = cookie_header_for_url(cookies, transfer_url)
        if cookie_header:
            transfer_headers["Cookie"] = cookie_header
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=transfer_url,
            headers=transfer_headers,
            # Provider pages round DataNodes sizes; the signed response is authoritative.
            expected_size=None,
            checksum=request.checksum,
            etag=request.etag,
            last_modified=request.last_modified,
            expires_at=request.expires_at,
            filename_hint=filename_from_url(source_url) or filename_from_url(transfer_url),
            range_supported=False,
            allowed_domains=_DATANODES_TRANSFER_DOMAINS,
        )

    async def _authenticate(
        self,
        *,
        username: str,
        password: str,
        cookies: httpx.Cookies,
    ) -> str | None:
        user_agent: str | None = None
        if self._login_solver is None:
            login_page = await request_bounded(
                self._http_client,
                "GET",
                _LOGIN_URL,
                resolver=self._resolver,
                allowed_domains=_DATANODES_DOMAINS,
                headers=_request_headers("text/html", user_agent=None),
                cookies=cookies,
            )
        else:
            solution = await self._login_solver(_LOGIN_URL)
            login_page, user_agent = _login_page_from_solution(solution, cookies=cookies)
        parsed = _validated_page(login_page)
        form = _login_form(parsed)
        if form is None or form.method != "POST":
            raise contract_changed()
        response = await request_bounded(
            self._http_client,
            "POST",
            urljoin(login_page.url, form.action or login_page.url),
            resolver=self._resolver,
            allowed_domains=_DATANODES_DOMAINS,
            headers=_request_headers("text/html", user_agent=user_agent),
            data={**form.fields, "login": username, "password": password},
            cookies=cookies,
        )
        response_page = _validated_page(response)
        if _login_form(response_page) is not None:
            if _INVALID_LOGIN_PATTERN.search(response.text):
                raise auth_required("DataNodes rejected the configured username or password.")
            raise auth_required()
        return user_agent

    async def _resolve_registered_download(
        self,
        page: BoundedArtifactResponse,
        *,
        source_url: str,
        cookies: httpx.Cookies,
        user_agent: str | None,
    ) -> str:
        current = page
        for _submission in range(_MAX_DOWNLOAD_FORM_SUBMISSIONS):
            parsed = _validated_page(current)
            transfer_url = _download_anchor(parsed, current.url) or _json_download_url(current)
            if transfer_url is not None:
                return transfer_url
            if _login_form(parsed) is not None:
                raise auth_required()
            component = _premium_download_component(current, source_url=source_url)
            if component is not None:
                headers = _request_headers(
                    "application/json",
                    user_agent=user_agent,
                )
                headers["Referer"] = current.url
                headers["X-Dn-Dl"] = "1"
                response = await request_bounded(
                    self._http_client,
                    "POST",
                    current.url,
                    resolver=self._resolver,
                    allowed_domains=_DATANODES_DOMAINS,
                    headers=headers,
                    files={name: (None, value) for name, value in component.fields.items()},
                    cookies=cookies,
                    max_redirects=0,
                )
                transfer_url = _json_download_url(response, decode=True)
                if transfer_url is None:
                    raise contract_changed()
                return transfer_url
            wait_seconds = _wait_seconds(current.text)
            form = _download_form(parsed)
            if form is None and wait_seconds:
                form = _dynamic_download_form(current, source_url=source_url)
            if form is None or form.method != "POST":
                raise contract_changed()
            if wait_seconds:
                await self._sleep(float(wait_seconds))
            form_data = dict(form.fields)
            if form_data.get("op") in {None, "download1"}:
                form_data["method_free"] = "Free Download"
            current = await request_bounded(
                self._http_client,
                "POST",
                urljoin(current.url, form.action or current.url),
                resolver=self._resolver,
                allowed_domains=_DATANODES_DOMAINS,
                headers=_request_headers(
                    "text/html, application/json",
                    user_agent=user_agent,
                ),
                data=form_data,
                cookies=cookies,
            )

        parsed = _validated_page(current)
        transfer_url = _download_anchor(parsed, current.url) or _json_download_url(current)
        if transfer_url is None:
            raise contract_changed()
        return transfer_url


def _login_page_from_solution(
    solution: DirectResolverResult,
    *,
    cookies: httpx.Cookies,
) -> tuple[BoundedArtifactResponse, str | None]:
    content = solution.html.encode("utf-8")
    if len(content) > _MAX_LOGIN_HTML_BYTES:
        raise contract_changed()
    user_agent = solution.user_agent
    if user_agent and ("\r" in user_agent or "\n" in user_agent):
        raise contract_changed()
    for cookie in solution.cookies:
        domain = (cookie.domain or "datanodes.to").lstrip(".").casefold()
        if domain != "datanodes.to" and not domain.endswith(".datanodes.to"):
            raise contract_changed()
        cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain or "datanodes.to",
            path=cookie.path or "/",
        )
    return (
        BoundedArtifactResponse(
            status_code=solution.status_code,
            headers=httpx.Headers({"Content-Type": "text/html; charset=utf-8"}),
            content=content,
            url=solution.final_url,
        ),
        user_agent,
    )


def _request_headers(accept: str, *, user_agent: str | None) -> dict[str, str]:
    headers = {"Accept": accept, "Referer": _DATANODES_REFERER}
    if user_agent:
        headers["User-Agent"] = user_agent
    return headers


def _validated_page(response: BoundedArtifactResponse) -> HostPageParser:
    parsed = parse_host_page(response.text)
    _reject_challenge(parsed)
    if response.status_code in {401, 403}:
        raise auth_required()
    if response.status_code != 200:
        raise contract_changed()
    return parsed


def _reject_challenge(parsed: HostPageParser) -> None:
    has_widget = bool(parsed.class_names & _CHALLENGE_CLASSES)
    has_challenge_form = bool(parsed.forms.keys() & _CHALLENGE_FORM_IDS)
    has_challenge_frame = any(
        "challenges.cloudflare.com" in source.casefold()
        or "recaptcha" in source.casefold()
        or "hcaptcha.com" in source.casefold()
        for source in parsed.iframe_sources
    )
    has_unsolved_field = any(
        name.casefold() in _CHALLENGE_FIELDS and not value.strip()
        for form in parsed.forms.values()
        for name, value in form.fields.items()
    )
    if has_widget or has_challenge_form or has_challenge_frame or has_unsolved_field:
        raise challenge_required()


def _login_form(parsed: HostPageParser) -> ParsedForm | None:
    return next(
        (form for form in parsed.forms.values() if form.fields.get("op") == "login"),
        None,
    )


def _download_form(parsed: HostPageParser) -> ParsedForm | None:
    named = parsed.forms.get("downloadForm")
    if named is not None:
        return named
    return next(
        (
            form
            for form in parsed.forms.values()
            if form.fields.get("op", "").startswith("download")
        ),
        None,
    )


def _dynamic_download_form(
    response: BoundedArtifactResponse,
    *,
    source_url: str,
) -> ParsedForm | None:
    """Reconstruct DataNodes' documented JS-injected second free form."""
    path_parts = [part for part in urlsplit(source_url).path.split("/") if part]
    if not path_parts or _FILE_ID_PATTERN.fullmatch(path_parts[0]) is None:
        return None
    rand_match = _RAND_PATTERN.search(response.text)
    return ParsedForm(
        action=response.url,
        method="POST",
        fields={
            "op": "download2",
            "id": path_parts[0],
            "rand": rand_match.group(1) if rand_match is not None else "",
            "referer": response.url,
            "method_free": "Free Download >>",
            "method_premium": "",
        },
    )


def _download_anchor(parsed: HostPageParser, base_url: str) -> str | None:
    raw_url = parsed.anchors.get("downloadbtn") or parsed.anchors.get("downloadButton")
    return urljoin(base_url, raw_url) if raw_url else None


def _premium_download_component(
    response: BoundedArtifactResponse,
    *,
    source_url: str,
) -> _PremiumDownloadComponent | None:
    parser = _DataNodesComponentParser()
    parser.feed(response.text)
    parser.close()
    if not parser.download_components:
        return None
    if len(parser.download_components) != 1:
        raise contract_changed()

    attributes = parser.download_components[0]
    if _component_bool(attributes, ":has-captcha"):
        raise challenge_required()
    if _component_bool(attributes, ":has-password"):
        raise challenge_required("The DataNodes file requires a download password.")
    if not _component_bool(attributes, ":is-premium"):
        raise auth_required("DataNodes Premium access is required for automated downloads.")
    if _component_bool(attributes, ":size-gated"):
        raise auth_required("The DataNodes account cannot download this file size.")

    path_parts = [part for part in urlsplit(source_url).path.split("/") if part]
    code = _component_value(attributes, "code", required=True)
    if not path_parts or code != path_parts[0] or _FILE_ID_PATTERN.fullmatch(code) is None:
        raise contract_changed()
    referer = _component_value(attributes, "referer", required=True)
    parsed_referer = urlsplit(referer)
    if parsed_referer.scheme not in {"http", "https"} or not parsed_referer.hostname:
        raise contract_changed()

    fields = {
        "op": "download2",
        "id": code,
        "rand": _component_value(attributes, "rand"),
        "referer": referer,
        "method_free": _component_value(attributes, "free-method"),
        "method_premium": _component_value(
            attributes,
            "premium-method",
            required=True,
        ),
        "g_captch__a": "1",
    }
    download_token = _component_value(attributes, "dl-token")
    if download_token:
        fields["dl_token"] = download_token
    return _PremiumDownloadComponent(fields=fields)


def _component_bool(attributes: Mapping[str, str], name: str) -> bool:
    value = attributes.get(name, "").casefold()
    if value not in {"true", "false"}:
        raise contract_changed()
    return value == "true"


def _component_value(
    attributes: Mapping[str, str],
    name: str,
    *,
    required: bool = False,
) -> str:
    value = attributes.get(name, "")
    if len(value) > _MAX_COMPONENT_VALUE_LENGTH or "\r" in value or "\n" in value:
        raise contract_changed()
    if required and not value:
        raise contract_changed()
    return value


def _json_download_url(
    response: BoundedArtifactResponse,
    *,
    decode: bool = False,
) -> str | None:
    content_type = response.headers.get("content-type", "").casefold()
    if "json" not in content_type and not response.text.lstrip().startswith("{"):
        return None
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_url = payload.get("url") or payload.get("download_url")
    if not isinstance(raw_url, str) or not raw_url:
        return None
    normalized = unquote(raw_url) if decode else raw_url
    return urljoin(response.url, normalized)


def _wait_seconds(document: str) -> int:
    for pattern in _WAIT_PATTERNS:
        match = pattern.search(document)
        if match is None:
            continue
        seconds = int(match.group(1))
        if seconds > _MAX_WAIT_SECONDS:
            raise contract_changed()
        return seconds
    return 0
