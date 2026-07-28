"""Small validation and parsing helpers for artifact-host adapters."""

from __future__ import annotations

import json
import re
from email.message import Message
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    HostResolutionRequest,
    credential_mode_for_host,
)
from pullbox.providers.artifact_hosts.registry import classify_artifact_host

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pullbox.providers.artifact_hosts.http import BoundedArtifactResponse

_CONTENT_RANGE_TOTAL = re.compile(r"^bytes\s+\d+-\d+/(\d+|\*)$", re.IGNORECASE)


def validate_resolution_request(
    request: HostResolutionRequest,
    *,
    expected_kind: DirectArtifactHostKind,
    credentials: Mapping[str, str],
) -> str:
    """Bind one adapter call to the declared host and credential family."""
    if request.host_kind is not expected_kind:
        raise candidate_invalid("artifact_host_kind_mismatch")
    url = request.final_url or request.share_url
    if not url or classify_artifact_host(url) is not expected_kind:
        raise candidate_invalid("artifact_host_kind_mismatch")
    credential_mode_for_host(expected_kind, credentials)
    return url


def parse_json_object(response: BoundedArtifactResponse) -> dict[str, object]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise contract_changed() from exc
    if not isinstance(payload, dict):
        raise contract_changed()
    return payload


def safe_filename(raw_name: object) -> str | None:
    if not isinstance(raw_name, str):
        return None
    name = unquote(raw_name).strip().replace("\\", "/")
    name = PurePosixPath(name).name.strip()
    if (
        not name
        or name in {".", ".."}
        or len(name) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        return None
    return name


def filename_from_url(url: str) -> str | None:
    return safe_filename(urlsplit(url).path)


def filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    message = Message()
    message["content-disposition"] = value
    return safe_filename(message.get_param("filename", header="content-disposition"))


def response_size(response: BoundedArtifactResponse, fallback: int | None) -> int | None:
    content_range = response.headers.get("content-range", "")
    match = _CONTENT_RANGE_TOTAL.fullmatch(content_range.strip())
    if match and match.group(1) != "*":
        return int(match.group(1))
    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit() and response.status_code != 206:
        return int(content_length)
    return fallback


def positive_int(value: object, *, maximum: int = 10 * 1024**4) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        return None
    return parsed if 0 <= parsed <= maximum else None


def contract_changed() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="artifact_host_contract_changed",
        message="The artifact host response no longer matches its supported contract.",
        failure_class=DirectArtifactFailureClass.PERMANENT_MIRROR,
        retryable=False,
        intervention=True,
    )


def candidate_invalid(code: str = "artifact_candidate_invalid") -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code=code,
        message="The provider artifact does not match the selected artifact host.",
        failure_class=DirectArtifactFailureClass.CANDIDATE_INVALID,
        retryable=False,
        intervention=True,
    )


def transient_host(code: str = "artifact_host_unavailable") -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code=code,
        message="The artifact host is temporarily unavailable.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )


def auth_required() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="artifact_host_auth_required",
        message="The artifact-host account session must be refreshed.",
        failure_class=DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED,
        retryable=False,
        intervention=True,
    )


def challenge_required() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="artifact_host_challenge",
        message="The artifact host requires interactive verification.",
        failure_class=DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE,
        retryable=False,
        intervention=True,
    )
