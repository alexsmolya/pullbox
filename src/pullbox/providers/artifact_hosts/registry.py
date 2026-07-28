"""Closed native registry for supported artifact-host URL families."""

from __future__ import annotations

from urllib.parse import urlsplit

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import ArtifactHostResolutionError

_MAX_ARTIFACT_URL_LENGTH = 4_000
_HOST_FAMILIES: tuple[tuple[DirectArtifactHostKind, frozenset[str]], ...] = (
    (
        DirectArtifactHostKind.PIXELDRAIN,
        frozenset({"pixeldrain.com", "pixeldrain.net"}),
    ),
    (
        DirectArtifactHostKind.MEGA,
        frozenset({"mega.nz", "mega.co.nz"}),
    ),
    (DirectArtifactHostKind.ROOTZ, frozenset({"rootz.so"})),
    (DirectArtifactHostKind.MEDIAFIRE, frozenset({"mediafire.com"})),
    (
        DirectArtifactHostKind.TERABOX,
        frozenset(
            {
                "1024terabox.com",
                "4funbox.com",
                "dubox.com",
                "mirrobox.com",
                "momerybox.com",
                "terabox.com",
                "teraboxapp.com",
                "teraboxlink.com",
                "terasharefile.com",
            }
        ),
    ),
    (DirectArtifactHostKind.DATANODES, frozenset({"datanodes.to"})),
)


def classify_artifact_host(raw_url: str) -> DirectArtifactHostKind:
    """Classify a safe HTTPS URL into the closed native host registry."""
    if (
        not isinstance(raw_url, str)
        or not raw_url.strip()
        or len(raw_url) > _MAX_ARTIFACT_URL_LENGTH
    ):
        raise _unsupported_url()
    try:
        parsed = urlsplit(raw_url.strip())
        _ = parsed.port
    except ValueError as exc:
        raise _unsupported_url() from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _unsupported_url()

    hostname = parsed.hostname.lower().rstrip(".")
    for host_kind, domains in _HOST_FAMILIES:
        if any(_is_domain_or_subdomain(hostname, domain) for domain in domains):
            return host_kind
    return DirectArtifactHostKind.GENERIC_HTTPS


def _is_domain_or_subdomain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _unsupported_url() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="unsupported_artifact_host",
        message="Artifact location must be a supported credential-free HTTPS URL.",
        failure_class=DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST,
        retryable=False,
        intervention=True,
    )
