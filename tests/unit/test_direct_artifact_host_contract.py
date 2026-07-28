"""Closed-registry and secret-boundary contracts for artifact hosts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostCredentialMode,
    ArtifactHostResolutionError,
    HostResolutionRequest,
    ResolvedTransfer,
    credential_mode_for_host,
    sanitize_provider_headers,
)
from pullbox.providers.artifact_hosts.registry import classify_artifact_host


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://pixeldrain.com/u/AbC123", DirectArtifactHostKind.PIXELDRAIN),
        ("https://pixeldrain.com/api/file/AbC123", DirectArtifactHostKind.PIXELDRAIN),
        ("https://mega.nz/file/example#key", DirectArtifactHostKind.MEGA),
        ("https://rootz.so/d/short-id", DirectArtifactHostKind.ROOTZ),
        (
            "https://www.mediafire.com/file/example/fixture.cbz/file",
            DirectArtifactHostKind.MEDIAFIRE,
        ),
        ("https://terabox.com/s/example", DirectArtifactHostKind.TERABOX),
        ("https://www.1024terabox.com/s/example", DirectArtifactHostKind.TERABOX),
        ("https://datanodes.to/example", DirectArtifactHostKind.DATANODES),
        ("https://s1.datanodes.to/d/example/fixture.cbz", DirectArtifactHostKind.DATANODES),
        ("https://files.example.test/fixture.cbz", DirectArtifactHostKind.GENERIC_HTTPS),
    ],
)
def test_closed_registry_classifies_supported_host_families(
    url: str,
    expected: DirectArtifactHostKind,
) -> None:
    assert classify_artifact_host(url) is expected


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.test/fixture.cbz",
        "ftp://files.example.test/fixture.cbz",
        "https://user:password@files.example.test/fixture.cbz",
        "https:///fixture.cbz",
        "not-a-url",
    ],
)
def test_registry_rejects_unsafe_or_malformed_locations(url: str) -> None:
    with pytest.raises(ArtifactHostResolutionError) as raised:
        classify_artifact_host(url)

    assert raised.value.failure_class is DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST
    assert url not in repr(raised.value)


def test_unknown_https_is_only_a_generic_transport_candidate() -> None:
    kind = classify_artifact_host("https://downloads.example.test/get?id=fixture")

    assert kind is DirectArtifactHostKind.GENERIC_HTTPS


@pytest.mark.parametrize(
    ("kind", "credentials", "expected"),
    [
        (DirectArtifactHostKind.GENERIC_HTTPS, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (DirectArtifactHostKind.PIXELDRAIN, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (
            DirectArtifactHostKind.PIXELDRAIN,
            {"api_key": "secret"},
            ArtifactHostCredentialMode.ACCOUNT,
        ),
        (DirectArtifactHostKind.MEGA, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (
            DirectArtifactHostKind.MEGA,
            {"session": "secret"},
            ArtifactHostCredentialMode.ACCOUNT,
        ),
        (DirectArtifactHostKind.ROOTZ, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (DirectArtifactHostKind.MEDIAFIRE, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (
            DirectArtifactHostKind.MEDIAFIRE,
            {"session": "secret"},
            ArtifactHostCredentialMode.ACCOUNT,
        ),
        (
            DirectArtifactHostKind.TERABOX,
            {"cookie": "secret"},
            ArtifactHostCredentialMode.ACCOUNT,
        ),
        (DirectArtifactHostKind.DATANODES, {}, ArtifactHostCredentialMode.ANONYMOUS),
        (
            DirectArtifactHostKind.DATANODES,
            {"premium_session": "secret"},
            ArtifactHostCredentialMode.ACCOUNT,
        ),
    ],
)
def test_host_credential_modes_are_explicit(
    kind: DirectArtifactHostKind,
    credentials: dict[str, str],
    expected: ArtifactHostCredentialMode,
) -> None:
    assert credential_mode_for_host(kind, credentials) is expected


def test_terabox_without_a_session_requires_visible_authentication() -> None:
    with pytest.raises(ArtifactHostResolutionError) as raised:
        credential_mode_for_host(DirectArtifactHostKind.TERABOX, {})

    assert raised.value.code == "artifact_host_auth_required"
    assert raised.value.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED
    assert raised.value.intervention is True


def test_provider_headers_keep_bounded_non_secret_hints_only() -> None:
    assert sanitize_provider_headers(
        {
            "Accept": "application/octet-stream",
            "Referer": "https://getcomics.org/fixture/",
            "User-Agent": "ignored provider agent",
        }
    ) == {
        "Accept": "application/octet-stream",
        "Referer": "https://getcomics.org/fixture/",
    }


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "Cookie",
        "Proxy-Authorization",
        "Host",
        "X-Forwarded-For",
        "Sec-Fetch-Site",
    ],
)
def test_provider_cannot_inject_sensitive_or_authority_headers(name: str) -> None:
    with pytest.raises(ArtifactHostResolutionError, match="provider header"):
        sanitize_provider_headers({name: "secret-value"})


def test_provider_referer_must_be_bounded_https_without_credentials() -> None:
    with pytest.raises(ArtifactHostResolutionError, match="Referer"):
        sanitize_provider_headers({"Referer": "http://source.example.test/"})

    with pytest.raises(ArtifactHostResolutionError, match="Referer"):
        sanitize_provider_headers({"Referer": "https://user:secret@source.example.test/"})


def test_resolution_and_transfer_representations_are_secret_free() -> None:
    request = HostResolutionRequest(
        artifact_identity="artifact-1",
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        share_url="https://pixeldrain.com/u/secret-id",
        final_url=None,
        provider_headers={"Referer": "https://source.example.test/secret-path"},
        expected_size=123,
        etag=None,
        last_modified=None,
        expires_at=None,
    )
    transfer = ResolvedTransfer(
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        url="https://pixeldrain.com/api/file/secret-id",
        headers={"Authorization": "Basic secret"},
        expected_size=123,
        etag='"fixture"',
        last_modified="Mon, 27 Jul 2026 00:00:00 GMT",
        expires_at=datetime(2026, 7, 28, tzinfo=UTC),
        filename_hint="fixture.cbz",
        range_supported=True,
    )

    rendered = repr((request, transfer))

    assert "secret-id" not in rendered
    assert "Basic secret" not in rendered
    assert "secret-path" not in rendered
    assert "fixture.cbz" in rendered


def test_resolution_error_never_renders_sensitive_context() -> None:
    error = ArtifactHostResolutionError(
        code="host_unavailable",
        message="Artifact host is temporarily unavailable.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
        sensitive_context={
            "url": "https://example.test/signed?token=secret",
            "authorization": "Bearer secret",
        },
    )

    rendered = repr(error)

    assert "token=secret" not in rendered
    assert "Bearer secret" not in rendered
    assert error.code == "host_unavailable"
    assert str(error) == "Artifact host is temporarily unavailable."
