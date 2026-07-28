"""Host-specific resolution contracts for native direct-download adapters."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    HostResolutionRequest,
)
from pullbox.providers.artifact_hosts.datanodes import DataNodesAdapter
from pullbox.providers.artifact_hosts.generic import GenericHttpsAdapter
from pullbox.providers.artifact_hosts.mediafire import MediaFireAdapter
from pullbox.providers.artifact_hosts.pixeldrain import PixelDrainAdapter
from pullbox.providers.artifact_hosts.rootz import RootzAdapter
from pullbox.providers.artifact_hosts.terabox import TeraBoxAdapter

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)
PIXELDRAIN_KEY = "pixeldrain-secret"
TERABOX_SESSION = "terabox-secret"


async def _resolve_public(_host: str, _port: int) -> Sequence[str]:
    return ["8.8.8.8"]


def _request(
    host_kind: DirectArtifactHostKind,
    url: str,
    *,
    final: bool = False,
    checksum: str | None = None,
) -> HostResolutionRequest:
    return HostResolutionRequest(
        artifact_identity="fixture-artifact",
        host_kind=host_kind,
        share_url=None if final else url,
        final_url=url if final else None,
        checksum=checksum,
    )


async def test_generic_https_accepts_a_probed_final_file_with_resume_validators() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Range"] == "bytes=0-0"
        return httpx.Response(
            206,
            headers={
                "Content-Type": "application/vnd.comicbook+zip",
                "Content-Range": "bytes 0-0/4096",
                "Content-Disposition": 'attachment; filename="fixture.cbz"',
                "ETag": '"fixture-etag"',
                "Last-Modified": "Mon, 27 Jul 2026 00:00:00 GMT",
            },
            content=b"P",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await GenericHttpsAdapter(client, resolver=_resolve_public).resolve(
            _request(
                DirectArtifactHostKind.GENERIC_HTTPS,
                "https://files.example.test/fixture.cbz",
                final=True,
                checksum="md5:11111111111111111111111111111111",
            ),
            credentials={},
        )

    assert transfer.expected_size == 4096
    assert transfer.filename_hint == "fixture.cbz"
    assert transfer.etag == '"fixture-etag"'
    assert transfer.checksum == "md5:11111111111111111111111111111111"
    assert transfer.range_supported is True


async def test_generic_https_rejects_an_html_landing_page() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html><title>Download</title></html>",
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await GenericHttpsAdapter(client, resolver=_resolve_public).resolve(
                _request(
                    DirectArtifactHostKind.GENERIC_HTTPS,
                    "https://files.example.test/download?id=fixture",
                    final=True,
                ),
                credentials={},
            )

    assert raised.value.code == "unsupported_landing_page"
    assert raised.value.failure_class is DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST
    assert raised.value.intervention is True


async def test_pixeldrain_resolves_public_or_account_downloads_from_file_info() -> None:
    seen_authorization: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("Authorization"))
        assert request.url.path == "/api/file/AbC123/info"
        return httpx.Response(
            200,
            json={
                "success": True,
                "id": "AbC123",
                "name": "fixture.cbz",
                "size": 8192,
                "mime_type": "application/vnd.comicbook+zip",
                "availability": "",
                "can_download": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        anonymous = await PixelDrainAdapter(client, resolver=_resolve_public).resolve(
            _request(DirectArtifactHostKind.PIXELDRAIN, "https://pixeldrain.com/u/AbC123"),
            credentials={},
        )
        account = await PixelDrainAdapter(client, resolver=_resolve_public).resolve(
            _request(DirectArtifactHostKind.PIXELDRAIN, "https://pixeldrain.com/u/AbC123"),
            credentials={"api_key": PIXELDRAIN_KEY},
        )

    expected_auth = "Basic " + base64.b64encode(f":{PIXELDRAIN_KEY}".encode()).decode()
    assert seen_authorization == [None, expected_auth]
    assert anonymous.expected_size == 8192
    assert anonymous.headers == {}
    assert account.headers == {"Authorization": expected_auth}
    assert account.filename_hint == "fixture.cbz"
    assert PIXELDRAIN_KEY not in repr(account)


@pytest.mark.parametrize(
    ("status", "code", "expected_class", "intervention"),
    [
        (
            403,
            "file_rate_limited_captcha_required",
            DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE,
            True,
        ),
        (403, "transfer_limit_exceeded", DirectArtifactFailureClass.HOST_QUOTA, True),
        (
            401,
            "authentication_failed",
            DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED,
            True,
        ),
        (500, "internal", DirectArtifactFailureClass.TRANSIENT_HOST, False),
    ],
)
async def test_pixeldrain_maps_stable_error_codes(
    status: int,
    code: str,
    expected_class: DirectArtifactFailureClass,
    intervention: bool,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            status,
            json={"success": False, "value": code, "message": "sensitive provider text"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await PixelDrainAdapter(client, resolver=_resolve_public).resolve(
                _request(DirectArtifactHostKind.PIXELDRAIN, "https://pixeldrain.com/u/AbC123"),
                credentials={"api_key": PIXELDRAIN_KEY},
            )

    assert raised.value.code == code
    assert raised.value.failure_class is expected_class
    assert raised.value.intervention is intervention
    assert "sensitive provider text" not in str(raised.value)
    assert PIXELDRAIN_KEY not in repr(raised.value)


async def test_rootz_resolves_short_id_to_uuid_then_ephemeral_signed_url() -> None:
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/d/short123":
            return httpx.Response(
                200,
                text=('<script>self.__next_f.push([1,"pageToken\\":\\"page-token-1\\"])</script>'),
                headers={"Content-Type": "text/html"},
            )
        if request.url.path == "/api/files/download-by-short":
            assert request.url.params["shortId"] == "short123"
            assert request.headers["X-Page-Token"] == "page-token-1"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "fileId": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "fixture.cbz",
                        "size": 16384,
                        "status": "active",
                        "downloadAllowed": True,
                    },
                },
            )
        assert request.url.path == "/api/files/download/550e8400-e29b-41d4-a716-446655440000"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "url": "https://cdn-files.alcyone.so/signed/fixture?token=secret",
                    "fileName": "fixture.cbz",
                    "size": 16384,
                    "mimeType": "application/octet-stream",
                    "expiresIn": 86400,
                    "expiresAt": None,
                    "shortId": "short123",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await RootzAdapter(
            client,
            resolver=_resolve_public,
            clock=lambda: NOW,
        ).resolve(
            _request(DirectArtifactHostKind.ROOTZ, "https://rootz.so/d/short123"),
            credentials={},
        )

    assert seen_paths == [
        "/d/short123",
        "/api/files/download-by-short",
        "/api/files/download/550e8400-e29b-41d4-a716-446655440000",
    ]
    assert transfer.expected_size == 16384
    assert transfer.expires_at == NOW + timedelta(days=1)
    assert transfer.filename_hint == "fixture.cbz"
    assert "token=secret" not in repr(transfer)


async def test_rootz_contract_drift_fails_without_guessing() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, text="<html>new layout</html>")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await RootzAdapter(client, resolver=_resolve_public).resolve(
                _request(DirectArtifactHostKind.ROOTZ, "https://rootz.so/d/short123"),
                credentials={},
            )

    assert raised.value.code == "artifact_host_contract_changed"
    assert raised.value.intervention is True


async def test_mediafire_resolves_the_bounded_public_download_anchor() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Cookie") is None
        return httpx.Response(
            200,
            text=(
                '<html><a id="downloadButton" '
                'href="https://download123.mediafire.com/a1/b2/fixture.cbz">Download</a></html>'
            ),
            headers={"Content-Type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await MediaFireAdapter(client, resolver=_resolve_public).resolve(
            _request(
                DirectArtifactHostKind.MEDIAFIRE,
                "https://www.mediafire.com/file/example/fixture.cbz/file",
            ),
            credentials={},
        )

    assert transfer.filename_hint == "fixture.cbz"
    assert transfer.headers == {}


async def test_mediafire_rejects_unsupported_browser_session_credentials() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: pytest.fail("network request made"))
    ) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await MediaFireAdapter(client, resolver=_resolve_public).resolve(
                _request(
                    DirectArtifactHostKind.MEDIAFIRE,
                    "https://www.mediafire.com/file/example/fixture.cbz/file",
                ),
                credentials={"session": "mediafire-secret"},
            )

    assert raised.value.code == "invalid_host_credentials"


async def test_terabox_follows_the_current_official_share_redirect() -> None:
    seen_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.headers["Host"])
        assert request.headers["Cookie"] == f"ndus={TERABOX_SESSION}"
        if request.headers["Host"] == "1024terabox.com":
            return httpx.Response(
                302,
                headers={"Location": "https://www.terabox.app/s/1fixture"},
            )
        if request.headers["Host"] == "www.terabox.app":
            return httpx.Response(
                200,
                text='<script>window.jsToken = "js-token";</script>',
                headers={"Content-Type": "text/html"},
            )
        assert request.url.path == "/share/list"
        return httpx.Response(
            200,
            json={
                "errno": 0,
                "list": [
                    {
                        "isdir": 0,
                        "server_filename": "fixture.cbz",
                        "size": 32768,
                        "dlink": "https://d.terabox.com/file/signed?token=secret",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
            _request(
                DirectArtifactHostKind.TERABOX,
                "https://1024terabox.com/s/1fixture",
            ),
            credentials={"session_token": TERABOX_SESSION},
        )

    assert seen_hosts == ["1024terabox.com", "www.terabox.app", "www.terabox.com"]
    assert transfer.expected_size == 32768


async def test_terabox_link_share_alias_is_supported() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Cookie"] == f"ndus={TERABOX_SESSION}"
        if request.url.path == "/s/1fixture":
            return httpx.Response(
                200,
                text='<script>window.jsToken = "js-token";</script>',
                headers={"Content-Type": "text/html"},
            )
        return httpx.Response(
            200,
            json={
                "errno": 0,
                "list": [
                    {
                        "isdir": 0,
                        "server_filename": "fixture.cbz",
                        "size": 32768,
                        "dlink": "https://d.terabox.com/file/signed?token=secret",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
            _request(DirectArtifactHostKind.TERABOX, "https://terabox.link/s/1fixture"),
            credentials={"session_token": TERABOX_SESSION},
        )

    assert transfer.expected_size == 32768


async def test_terabox_extracts_the_current_percent_encoded_js_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Cookie"] == f"ndus={TERABOX_SESSION}"
        if request.url.path == "/s/1fixture":
            return httpx.Response(
                200,
                text=(
                    "<script>try { eval(decodeURIComponent(`"
                    "function%20fn(a)%7Bwindow.jsToken%20%3D%20a%7D%3B"
                    "fn(%22encoded-js-token%22)`)) } catch (ex) {}</script>"
                ),
                headers={"Content-Type": "text/html"},
            )
        assert request.url.path == "/share/list"
        assert request.url.params["jsToken"] == "encoded-js-token"
        return httpx.Response(
            200,
            json={
                "errno": 0,
                "list": [
                    {
                        "isdir": 0,
                        "server_filename": "fixture.cbz",
                        "size": 32768,
                        "dlink": "https://d.terabox.com/file/signed?token=secret",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
            _request(DirectArtifactHostKind.TERABOX, "https://www.1024tera.com/s/1fixture"),
            credentials={"session_token": TERABOX_SESSION},
        )

    assert transfer.expected_size == 32768


async def test_terabox_session_resolves_share_metadata_to_a_direct_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Cookie"] == f"ndus={TERABOX_SESSION}"
        if request.url.path == "/s/1fixture":
            return httpx.Response(
                200,
                text='<script>window.jsToken = "js-token";</script>',
                headers={"Content-Type": "text/html"},
            )
        assert request.url.path == "/share/list"
        assert request.url.params["shorturl"] == "fixture"
        assert request.url.params["jsToken"] == "js-token"
        return httpx.Response(
            200,
            json={
                "errno": 0,
                "list": [
                    {
                        "isdir": 0,
                        "fs_id": 123,
                        "server_filename": "fixture.cbz",
                        "size": 32768,
                        "dlink": "https://d.terabox.com/file/signed?token=secret",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
            _request(DirectArtifactHostKind.TERABOX, "https://www.terabox.com/s/1fixture"),
            credentials={"cookie": TERABOX_SESSION},
        )

    assert transfer.expected_size == 32768
    assert transfer.filename_hint == "fixture.cbz"
    assert transfer.headers == {"Cookie": f"ndus={TERABOX_SESSION}"}
    assert TERABOX_SESSION not in repr(transfer)


async def test_terabox_expired_session_requires_reauthentication() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            401,
            json={"errno": -6, "errmsg": "session expired"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
                _request(DirectArtifactHostKind.TERABOX, "https://terabox.com/s/1fixture"),
                credentials={"cookie": TERABOX_SESSION},
            )

    assert raised.value.code == "artifact_host_auth_required"
    assert raised.value.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED
    assert TERABOX_SESSION not in repr(raised.value)


async def test_terabox_missing_direct_link_requires_reauthentication() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s/1fixture":
            return httpx.Response(
                200,
                text='<script>window.jsToken = "js-token";</script>',
                headers={"Content-Type": "text/html"},
            )
        return httpx.Response(
            200,
            json={
                "errno": 0,
                "list": [
                    {
                        "isdir": 0,
                        "server_filename": "fixture.cbz",
                        "size": 32768,
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await TeraBoxAdapter(client, resolver=_resolve_public).resolve(
                _request(DirectArtifactHostKind.TERABOX, "https://terabox.com/s/1fixture"),
                credentials={"cookie": TERABOX_SESSION},
            )

    assert raised.value.code == "artifact_host_auth_required"
    assert raised.value.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED
    assert TERABOX_SESSION not in repr(raised.value)


async def test_datanodes_free_flow_posts_once_and_returns_the_final_file() -> None:
    seen_methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200,
                text=(
                    '<form id="downloadForm" method="POST" action="/download">'
                    '<input type="hidden" name="op" value="download1">'
                    '<input type="hidden" name="id" value="fixture">'
                    '<input type="hidden" name="rand" value="fixture-rand">'
                    '<button id="method_free">Continue</button></form>'
                ),
                headers={"Content-Type": "text/html"},
            )
        assert request.url.path == "/download"
        assert b"op=download1" in request.content
        return httpx.Response(
            200,
            text=(
                '<html><a id="downloadbtn" '
                'href="https://s1.datanodes.to/d/fixture/fixture.cbz">Download</a></html>'
            ),
            headers={"Content-Type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transfer = await DataNodesAdapter(client, resolver=_resolve_public).resolve(
            _request(
                DirectArtifactHostKind.DATANODES,
                "https://datanodes.to/fixture/fixture.cbz",
            ),
            credentials={},
        )

    assert seen_methods == ["GET", "POST"]
    assert transfer.filename_hint == "fixture.cbz"


async def test_datanodes_challenge_enters_visible_intervention() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            text='<div class="cf-turnstile" data-sitekey="fixture"></div>',
            headers={"Content-Type": "text/html"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ArtifactHostResolutionError) as raised:
            await DataNodesAdapter(client, resolver=_resolve_public).resolve(
                _request(
                    DirectArtifactHostKind.DATANODES,
                    "https://datanodes.to/fixture/fixture.cbz",
                ),
                credentials={},
            )

    assert raised.value.code == "artifact_host_challenge"
    assert raised.value.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE
    assert raised.value.intervention is True
