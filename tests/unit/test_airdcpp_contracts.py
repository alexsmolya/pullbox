"""AirDC++ wire-contract parser tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pullbox.providers.airdcpp.contracts import (
    AirDcppAuthenticationInfo,
    AirDcppConnectivityInfo,
    AirDcppHub,
    AirDcppQueueBundle,
    AirDcppSession,
    AirDcppSystemInfo,
)


def _system_info(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "api_version": 1,
        "api_feature_level": 10,
        "client_version": "AirDC++w 2.14.0 x86_64",
        "platform": "linux",
        "path_separator": "/",
    }
    value.update(overrides)
    return value


def _user(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "username": "pullbox",
        "permissions": [
            "search",
            "download",
            "queue_view",
            "queue_edit",
            "hubs_view",
            "settings_view",
        ],
    }
    value.update(overrides)
    return value


def test_authentication_contract_accepts_additive_fields_and_masks_token() -> None:
    auth = AirDcppAuthenticationInfo.model_validate(
        {
            "session_id": 123,
            "auth_token": "memory-only-token",
            "token_type": "Bearer",
            "system_info": {**_system_info(), "future_field": "accepted"},
            "user": {**_user(), "active_sessions": 1},
            "wizard_pending": False,
            "future_envelope_field": True,
        }
    )

    assert auth.session_id == 123
    assert auth.auth_token.get_secret_value() == "memory-only-token"
    assert "memory-only-token" not in repr(auth)
    assert auth.system_info.api_feature_level == 10


@pytest.mark.parametrize(
    "payload",
    [
        {},
        _system_info(api_version="1"),
        _system_info(api_feature_level=True),
        _system_info(path_separator=1),
    ],
)
def test_system_info_rejects_missing_or_wrong_required_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AirDcppSystemInfo.model_validate(payload)


def test_session_contract_requires_current_user() -> None:
    with pytest.raises(ValidationError):
        AirDcppSession.model_validate({"id": 123})


def test_hub_contract_keeps_sensitive_url_masked() -> None:
    hub = AirDcppHub.model_validate(
        {
            "id": 5,
            "hub_url": "adcs://private.example.test:1511",
            "connect_state": {"id": "connected", "str": "Connected"},
            "identity": {"name": "Private hub", "description": "", "supports": []},
            "share_profile": {},
            "favorite_hub": 0,
            "message_counts": {},
            "settings": {},
        }
    )

    assert hub.connected is True
    assert "private.example.test" not in repr(hub)


def test_connectivity_contract_requires_valid_ports_and_statuses() -> None:
    connectivity = AirDcppConnectivityInfo.model_validate(
        {
            "status_v4": {
                "auto_detect": True,
                "enabled": True,
                "text": "Active mode",
                "bind_address": "0.0.0.0",
                "external_ip": "203.0.113.10",
            },
            "status_v6": {
                "auto_detect": False,
                "enabled": False,
                "text": "Disabled",
                "bind_address": "::",
                "external_ip": "::",
            },
            "tcp_port": 21248,
            "tls_port": 21249,
            "udp_port": 21248,
        }
    )

    assert connectivity.status_v4.enabled is True
    assert connectivity.tcp_port == 21248
    assert "203.0.113.10" not in repr(connectivity)

    with pytest.raises(ValidationError):
        AirDcppConnectivityInfo.model_validate(
            {
                **connectivity.model_dump(),
                "tcp_port": 70000,
            }
        )


def test_queue_bundle_contract_requires_authoritative_progress_fields() -> None:
    bundle = AirDcppQueueBundle.model_validate(
        {
            "id": 83425443,
            "name": "Example Comic 001.cbz",
            "target": "/Downloads/Example Comic 001.cbz",
            "type": {"id": "file", "str": "cbz", "content_type": {"id": "other"}},
            "size": 1000,
            "downloaded_bytes": 250,
            "priority": {"id": 4, "str": "Normal", "auto": False},
            "time_added": 1,
            "time_finished": 0,
            "speed": 10,
            "seconds_left": 75,
            "sources": {"online": 1, "total": 2, "str": "1/2 online"},
            "status": {
                "id": "queued",
                "failed": False,
                "downloaded": False,
                "completed": False,
                "str": "Running (25%)",
            },
            "future_field": "accepted",
        }
    )

    assert bundle.id == 83425443
    assert bundle.status.completed is False

    with pytest.raises(ValidationError):
        AirDcppQueueBundle.model_validate(
            {
                "id": 1,
                "name": "Incomplete",
            }
        )
