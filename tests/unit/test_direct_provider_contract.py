from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from pullbox.providers.direct.contract import (
    DIRECT_PROVIDER_PROTOCOL_V1,
    DirectManifestResponse,
    DirectMirror,
    DirectResolveResponse,
    DirectSearchRequest,
    DirectSearchResponse,
    negotiate_direct_provider_protocol,
)


def _manifest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
        "provider_id": "pullbox.synthetic",
        "display_name": "Synthetic Provider",
        "description": "Deterministic test provider.",
        "provider_version": "1.0.0",
        "supported_protocol_versions": [DIRECT_PROVIDER_PROTOCOL_V1],
        "publisher": "Pullbox",
        "license": "GPL-3.0-or-later",
        "source_domains": ["provider.test"],
        "artifact_host_patterns": [],
        "capabilities": {
            "search": True,
            "resolve": True,
            "browser_challenge": False,
            "health": True,
            "quota": False,
            "configuration_schema": True,
        },
        "configuration_schema": {
            "type": "object",
            "properties": {
                "member_token": {
                    "type": "string",
                    "title": "Member token",
                    "x-pullbox-secret": True,
                }
            },
            "additionalProperties": False,
        },
        "build": {"revision": "test"},
    }
    payload.update(overrides)
    return payload


def test_manifest_accepts_additive_fields_and_normalizes_native_controls() -> None:
    manifest = DirectManifestResponse.model_validate(
        _manifest(future_optional_field={"supported": True})
    )

    assert manifest.provider_id == "pullbox.synthetic"
    assert manifest.configuration_controls[0].name == "member_token"
    assert manifest.configuration_controls[0].secret is True


def test_manifest_normalizes_allowlisted_uri_controls() -> None:
    manifest = DirectManifestResponse.model_validate(
        _manifest(
            configuration_schema={
                "type": "object",
                "properties": {
                    "source_url": {
                        "type": "string",
                        "title": "Official URL",
                        "format": "uri",
                        "enum": [
                            "https://annas-archive.gl",
                            "https://annas-archive.pk",
                            "https://annas-archive.gd",
                        ],
                        "default": "https://annas-archive.gd",
                    }
                },
                "additionalProperties": False,
            }
        )
    )

    control = manifest.configuration_controls[0]
    assert control.input_format == "uri"
    assert control.choices == (
        "https://annas-archive.gl",
        "https://annas-archive.pk",
        "https://annas-archive.gd",
    )


def test_manifest_rejects_executable_or_nested_configuration_controls() -> None:
    with pytest.raises(ValidationError, match="configuration control is unsupported"):
        DirectManifestResponse.model_validate(
            _manifest(
                configuration_schema={
                    "type": "object",
                    "properties": {"unsafe": {"type": "object", "html": "<script>"}},
                    "additionalProperties": False,
                }
            )
        )


@pytest.mark.parametrize(
    "field",
    [
        {"type": "integer", "default": True},
        {"type": "boolean", "enum": ["yes", "no"]},
        {"type": "integer", "minimum": 10, "maximum": 1},
        {"type": "string", "minLength": 10, "maxLength": 1},
        {"type": "integer", "minLength": 1},
        {"type": "string", "minimum": 1},
        {"type": "string", "format": "html"},
        {"type": "boolean", "format": "uri"},
        {"type": "string", "format": "uri", "x-pullbox-secret": True},
    ],
)
def test_manifest_rejects_internally_inconsistent_configuration_controls(
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DirectManifestResponse.model_validate(
            _manifest(
                configuration_schema={
                    "type": "object",
                    "properties": {"unsafe": field},
                    "additionalProperties": False,
                }
            )
        )


def test_protocol_negotiation_requires_exact_supported_intersection() -> None:
    assert (
        negotiate_direct_provider_protocol([DIRECT_PROVIDER_PROTOCOL_V1])
        == DIRECT_PROVIDER_PROTOCOL_V1
    )
    with pytest.raises(ValueError, match="compatible"):
        negotiate_direct_provider_protocol(["direct-download-provider/v2"])


def test_search_request_requires_aware_future_deadline() -> None:
    with pytest.raises(ValidationError):
        DirectSearchRequest(
            protocol_version=DIRECT_PROVIDER_PROTOCOL_V1,
            request_id=UUID("11111111-1111-4111-8111-111111111111"),
            deadline=datetime.now() + timedelta(minutes=1),
            intent={
                "series_title": "Synthetic Adventures",
                "normalized_title": "synthetic adventures",
            },
        )


def test_search_and_resolve_responses_are_bounded() -> None:
    with pytest.raises(ValidationError):
        DirectSearchResponse.model_validate(
            {
                "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
                "request_id": "11111111-1111-4111-8111-111111111111",
                "candidates": [{}] * 101,
                "truncated": True,
            }
        )
    with pytest.raises(ValidationError):
        DirectResolveResponse.model_validate(
            {
                "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
                "request_id": "22222222-2222-4222-8222-222222222222",
                "artifacts": [{}] * 101,
            }
        )


def test_source_credentials_are_hidden_from_request_repr() -> None:
    request = DirectSearchRequest(
        protocol_version=DIRECT_PROVIDER_PROTOCOL_V1,
        request_id=UUID("11111111-1111-4111-8111-111111111111"),
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        intent={
            "series_title": "Synthetic Adventures",
            "normalized_title": "synthetic adventures",
        },
        source_credentials={"member_token": "unique-secret-value"},
    )

    assert "unique-secret-value" not in repr(request)


def test_signed_artifact_locations_are_hidden_from_repr() -> None:
    mirror = DirectMirror(
        mirror_id="mirror-1",
        host_kind="generic_https",
        final_url="https://files.example/book.cbz?token=unique-signed-value",
    )

    assert "unique-signed-value" not in repr(mirror)
