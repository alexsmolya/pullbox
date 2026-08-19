"""Domain and persistence contracts for dormant direct acquisition records."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
    DirectHostAccountState,
    DirectHostConfig,
    DirectHostOperationalResult,
    DirectHostReachabilityState,
    DirectProviderConfig,
    DirectProviderState,
    DirectProviderTrustLevel,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.series import Series, SeriesStatus, SeriesType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_issue(session: AsyncSession) -> Issue:
    series = Series(
        comicvine_id=991_001,
        title="Direct Test",
        sort_title="Direct Test",
        year_start=2026,
        status=SeriesStatus.CONTINUING,
        series_type=SeriesType.STANDARD,
        monitored=True,
        issue_count=1,
    )
    session.add(series)
    await session.flush()
    issue = Issue(
        series_id=series.id,
        comicvine_id=992_001,
        issue_number=1,
        status=IssueStatus.WANTED,
        issue_type=IssueType.ISSUE,
    )
    session.add(issue)
    await session.flush()
    return issue


def test_direct_domain_enum_values_are_stable() -> None:
    assert {value.value for value in DirectProviderState} == {
        "disabled",
        "healthy",
        "degraded",
        "rate_limited",
        "authentication_required",
        "incompatible",
        "unavailable",
    }
    assert {value.value for value in DirectProviderTrustLevel} == {
        "verified_pullbox",
        "custom",
    }
    assert {value.value for value in DirectArtifactHostKind} == {
        "generic_https",
        "pixeldrain",
        "mega",
        "rootz",
        "mediafire",
        "terabox",
        "datanodes",
    }
    assert {value.value for value in DirectHostAccountState} == {
        "not_configured",
        "unknown",
        "healthy",
        "authentication_required",
        "quota_limited",
        "unavailable",
    }
    assert {value.value for value in DirectHostReachabilityState} == {
        "not_checked",
        "reachable",
        "not_reachable",
        "authentication_required",
        "quota_limited",
        "unavailable",
    }
    assert {value.value for value in DirectHostOperationalResult} == {
        "successful",
        "failed",
    }
    assert {value.value for value in DirectArtifactRouteKind} == {
        "direct",
        "torrent_file",
        "magnet",
    }
    assert "artifact_host_auth_required" in {value.value for value in DirectArtifactFailureClass}
    assert "artifact_host_challenge" in {value.value for value in DirectArtifactFailureClass}
    assert "unsafe_route" in {value.value for value in DirectArtifactFailureClass}


def test_direct_models_expose_required_defaults_and_indexes() -> None:
    provider_columns = DirectProviderConfig.__table__.columns
    host_columns = DirectHostConfig.__table__.columns
    acquisition_columns = DirectAcquisitionAttempt.__table__.columns
    artifact_columns = DirectArtifactAttempt.__table__.columns

    assert provider_columns["enabled"].default.arg is False
    assert provider_columns["priority"].default.arg == 50
    assert provider_columns["state"].default.arg is DirectProviderState.DISABLED
    assert host_columns["account_state"].default.arg is DirectHostAccountState.NOT_CONFIGURED
    assert host_columns["reachability_state"].default.arg is DirectHostReachabilityState.NOT_CHECKED
    assert acquisition_columns["state"].default.arg is DirectAcquisitionState.DISCOVERED
    assert acquisition_columns["progress_revision"].default.arg == 0
    assert artifact_columns["state"].default.arg is DirectArtifactState.PLANNED
    assert artifact_columns["bytes_transferred"].default.arg == 0

    assert {
        "ix_direct_provider_configs_state",
        "ix_direct_provider_configs_enabled_priority",
    }.issubset({index.name for index in DirectProviderConfig.__table__.indexes})
    assert {
        "ix_direct_acquisition_attempts_state_retry",
        "ix_direct_acquisition_attempts_issue_created",
        "ix_direct_acquisition_attempts_provider_state",
    }.issubset({index.name for index in DirectAcquisitionAttempt.__table__.indexes})

    recovery_index = next(
        index
        for index in DirectAcquisitionAttempt.__table__.indexes
        if index.name == "ix_direct_acquisition_attempts_state_retry"
    )
    assert [column.name for column in recovery_index.columns] == ["state", "next_retry_at"]


def test_direct_enum_columns_store_lowercase_values_portably() -> None:
    enum_columns = (
        DirectProviderConfig.__table__.columns["state"],
        DirectHostConfig.__table__.columns["host_kind"],
        DirectAcquisitionAttempt.__table__.columns["state"],
        DirectArtifactAttempt.__table__.columns["route_kind"],
    )

    for column in enum_columns:
        assert column.type.native_enum is False
        assert all(value == value.lower() for value in column.type.enums)


def test_direct_model_relationships_match_ownership_boundaries() -> None:
    provider_relationships = {item.key for item in inspect(DirectProviderConfig).relationships}
    acquisition_relationships = {
        item.key for item in inspect(DirectAcquisitionAttempt).relationships
    }
    artifact_relationships = {item.key for item in inspect(DirectArtifactAttempt).relationships}

    assert "acquisition_attempts" in provider_relationships
    assert {
        "issue",
        "search_log",
        "provider_config",
        "library_file",
        "artifact_attempts",
    }.issubset(acquisition_relationships)
    assert "acquisition_attempt" in artifact_relationships

    artifact_cascade = inspect(DirectAcquisitionAttempt).relationships["artifact_attempts"].cascade
    assert "delete-orphan" in artifact_cascade


def test_direct_foreign_key_delete_behavior_is_explicit() -> None:
    expected = {
        "issue_id": "CASCADE",
        "search_log_id": "SET NULL",
        "provider_config_id": "SET NULL",
        "library_file_id": "SET NULL",
    }
    for column_name, ondelete in expected.items():
        foreign_key = next(
            iter(DirectAcquisitionAttempt.__table__.columns[column_name].foreign_keys)
        )
        assert foreign_key.ondelete == ondelete

    artifact_fk = next(
        iter(DirectArtifactAttempt.__table__.columns["acquisition_attempt_id"].foreign_keys)
    )
    assert artifact_fk.ondelete == "CASCADE"


@pytest.mark.asyncio
async def test_direct_attempt_round_trip_preserves_only_safe_snapshots(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_factory() as session:
        issue = await _seed_issue(session)
        provider = DirectProviderConfig(
            provider_id="getcomics",
            display_name="GetComics",
            endpoint="http://provider:8080",
            encrypted_bearer_token="enc:ciphertext",
            encrypted_configuration={"member_key": "enc:source-ciphertext"},
            configuration_metadata={"member_key": {"configured": True}},
            manifest_snapshot={"protocol_versions": ["direct-download-provider/v1"]},
        )
        session.add(provider)
        await session.flush()

        attempt = DirectAcquisitionAttempt(
            request_key="manual:issue:1:request-1",
            issue_id=issue.id,
            provider_config_id=provider.id,
            provider_identity="getcomics",
            provider_candidate_id="candidate-1",
            requested_coverage={"issue_ids": [issue.id]},
            candidate_snapshot={"title": "Direct Test 001", "format": "cbz"},
            plan_snapshot={"selected_artifact": "artifact-1", "host": "pixeldrain"},
        )
        attempt.artifact_attempts.append(
            DirectArtifactAttempt(
                sequence_no=0,
                artifact_identity="artifact-1",
                route_kind=DirectArtifactRouteKind.DIRECT,
                host_kind=DirectArtifactHostKind.PIXELDRAIN,
                expected_size=123_456,
            )
        )
        session.add(attempt)
        await session.commit()
        attempt_id = attempt.id

    async with db_factory() as session:
        result = (
            await session.execute(
                select(DirectAcquisitionAttempt).where(DirectAcquisitionAttempt.id == attempt_id)
            )
        ).scalar_one()
        assert result.provider_identity == "getcomics"
        assert result.requested_coverage == {"issue_ids": [result.issue_id]}
        assert result.plan_snapshot == {
            "selected_artifact": "artifact-1",
            "host": "pixeldrain",
        }
        assert len(result.artifact_attempts) == 1
        assert result.artifact_attempts[0].host_kind is DirectArtifactHostKind.PIXELDRAIN


@pytest.mark.asyncio
async def test_deleting_attempt_cascades_owned_artifacts(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_factory() as session:
        issue = await _seed_issue(session)
        attempt = DirectAcquisitionAttempt(
            request_key="manual:issue:1:request-2",
            issue_id=issue.id,
            provider_identity="synthetic",
            provider_candidate_id="candidate-2",
        )
        artifact = DirectArtifactAttempt(
            sequence_no=0,
            artifact_identity="artifact-2",
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        )
        attempt.artifact_attempts.append(artifact)
        session.add(attempt)
        await session.commit()
        attempt_id = attempt.id
        artifact_id = artifact.id

    async with db_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, attempt_id)
        assert attempt is not None
        await session.delete(attempt)
        await session.commit()

    async with db_factory() as session:
        assert await session.get(DirectArtifactAttempt, artifact_id) is None
