"""Persistence contracts for the optional direct-download browser resolver."""

from sqlalchemy import inspect

from pullbox.models.direct_acquisition import DirectResolverConfig, DirectResolverState


def test_direct_resolver_state_values_are_stable() -> None:
    assert {value.value for value in DirectResolverState} == {
        "disabled",
        "unknown",
        "healthy",
        "degraded",
        "authentication_required",
        "incompatible",
        "unavailable",
    }


def test_direct_resolver_model_is_a_bounded_singleton_configuration() -> None:
    columns = DirectResolverConfig.__table__.columns

    assert columns["name"].default.arg == "default"
    assert columns["enabled"].default.arg is False
    assert columns["state"].default.arg is DirectResolverState.DISABLED
    assert columns["allow_private_http"].default.arg is False
    assert columns["timeout_seconds"].default.arg == 60
    assert columns["max_concurrency"].default.arg == 1
    assert callable(columns["encrypted_auth_headers"].default.arg)

    constraints = {item.name for item in DirectResolverConfig.__table__.constraints}
    assert "uq_direct_resolver_name" in constraints
    assert "ck_direct_resolver_timeout" in constraints
    assert "ck_direct_resolver_concurrency" in constraints


def test_direct_resolver_has_no_relationship_to_provider_or_acquisition_rows() -> None:
    assert list(inspect(DirectResolverConfig).relationships) == []


def test_direct_resolver_enum_is_portable_lowercase_text() -> None:
    column = DirectResolverConfig.__table__.columns["state"]

    assert column.type.native_enum is False
    assert column.type.enums == [
        "disabled",
        "unknown",
        "healthy",
        "degraded",
        "authentication_required",
        "incompatible",
        "unavailable",
    ]
