"""AirDC++ runtime composition and feature-flag isolation contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pullbox.composition.airdcpp import (
    build_airdcpp_supervisor_configs,
    start_airdcpp_supervisor_registry,
)


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _Session:
    def __init__(self, clients: list[object]) -> None:
        self.clients = clients
        self.execute_calls = 0

    async def execute(self, _statement: object) -> _Result:
        self.execute_calls += 1
        return _Result(self.clients)

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Registry:
    def __init__(self, **_kwargs: object) -> None:
        self.applied: tuple[object, ...] = ()
        self.stopped = False

    async def apply(self, configs: tuple[object, ...]) -> None:
        self.applied = configs

    async def stop(self) -> None:
        self.stopped = True


def _client() -> SimpleNamespace:
    return SimpleNamespace(
        id=12,
        name="Dedicated Air",
        url="http://airdcpp-vpn:5600",
        username="pullbox",
        password="encrypted-password",
        enabled=True,
        airdcpp_settings=SimpleNamespace(request_timeout_seconds=20),
    )


@pytest.mark.asyncio
async def test_composition_loads_only_bounded_exact_client_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session([_client()])
    monkeypatch.setattr(
        "pullbox.composition.airdcpp.decrypt_secret",
        lambda value: "decrypted" if value == "encrypted-password" else "wrong",
    )

    configs = await build_airdcpp_supervisor_configs(session)  # type: ignore[arg-type]

    assert len(configs) == 1
    config = configs[0]
    assert config.config_id == 12
    assert config.client_identity == "airdcpp:12"
    assert config.base_url == "http://airdcpp-vpn:5600"
    assert config.password.get_secret_value() == "decrypted"
    assert config.request_timeout_seconds == 20


@pytest.mark.asyncio
async def test_feature_off_starts_no_session_query_or_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def session_factory() -> Any:
        calls.append("session")
        return _Session([_client()])

    monkeypatch.setattr("pullbox.composition.airdcpp.AirDcppSupervisorRegistry", _Registry)

    registry = await start_airdcpp_supervisor_registry(
        session_factory,
        enabled=False,
    )

    assert calls == []
    assert registry is None


@pytest.mark.asyncio
async def test_feature_on_loads_configs_and_schedules_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session([_client()])
    monkeypatch.setattr("pullbox.composition.airdcpp.decrypt_secret", lambda _value: "decrypted")
    monkeypatch.setattr("pullbox.composition.airdcpp.AirDcppSupervisorRegistry", _Registry)

    registry = await start_airdcpp_supervisor_registry(lambda: session, enabled=True)

    assert isinstance(registry, _Registry)
    assert len(registry.applied) == 1
    assert session.execute_calls == 1
