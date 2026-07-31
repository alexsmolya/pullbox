"""Planning direct candidates into restart-safe acquisition attempts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
    DirectArtifactState,
    DirectHostAccountState,
    DirectHostConfig,
    DirectProviderConfig,
    DirectProviderState,
    DirectResolverKind,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.direct.client import DirectProviderClientError
from pullbox.providers.direct.contract import (
    DirectArtifact,
    DirectArtifactCoverage,
    DirectArtifactRoute,
    DirectMirror,
    DirectResolveResponse,
    DirectResolverProfile,
)
from pullbox.services.blocklist_service import BlocklistService
from pullbox.services.direct_acquisition_planner_service import (
    DirectAcquisitionPlanningError,
    direct_route_identity,
    plan_direct_acquisition,
    resolve_planned_artifact_source,
)
from pullbox.services.direct_resolver_service import ProviderResolverOption

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        series = Series(
            id=1,
            comicvine_id=800_001,
            title="Planner Series",
            sort_title="Planner Series",
            year_start=2026,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        db_session.add(series)
        db_session.add(
            Issue(
                id=1,
                series_id=1,
                comicvine_id=800_002,
                issue_number=1,
                issue_type=IssueType.ISSUE,
                status=IssueStatus.WANTED,
            )
        )
        provider = DirectProviderConfig(
            id=1,
            provider_id="community.getcomics",
            display_name="GetComics",
            endpoint="http://provider:8080",
            enabled=True,
            priority=10,
            state=DirectProviderState.HEALTHY,
            negotiated_protocol="direct-download-provider/v1",
            encrypted_bearer_token="unused-in-test",
            configuration_metadata={"allow_private_http": True, "public_values": {}},
            manifest_snapshot={"source_domains": ["getcomics.org"]},
        )
        db_session.add(provider)
        db_session.add_all(
            [
                DirectHostConfig(
                    host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
                    enabled=True,
                    preference=20,
                    account_state=DirectHostAccountState.NOT_CONFIGURED,
                ),
                DirectHostConfig(
                    host_kind=DirectArtifactHostKind.PIXELDRAIN,
                    enabled=True,
                    preference=10,
                    account_state=DirectHostAccountState.HEALTHY,
                ),
                DirectHostConfig(
                    host_kind=DirectArtifactHostKind.TERABOX,
                    enabled=True,
                    preference=5,
                    account_state=DirectHostAccountState.AUTHENTICATION_REQUIRED,
                ),
            ]
        )
        db_session.add(
            DirectAcquisitionAttempt(
                id=1,
                request_key="direct-search:test",
                issue_id=1,
                provider_config_id=1,
                provider_identity="community.getcomics",
                provider_candidate_id="candidate-1",
                state=DirectAcquisitionState.DISCOVERED,
                requested_coverage={"issue_numbers": ["1"], "issue_type": "issue"},
                candidate_snapshot={"display_title": "Planner Series 001 (2026)"},
                plan_snapshot={},
                progress_snapshot={"stage": "discovered"},
            )
        )
        await db_session.commit()
        yield db_session
    await engine.dispose()


def _response(*, reverse: bool = False) -> DirectResolveResponse:
    mirrors = [
        DirectMirror(
            mirror_id="generic-mirror",
            host_kind="generic_https",
            final_url="https://files.example.test/signed.cbz?token=hidden",
            size_bytes=100,
        ),
        DirectMirror(
            mirror_id="pixel-mirror",
            host_kind="pixeldrain",
            share_url="https://pixeldrain.com/u/abc123",
            size_bytes=100,
            checksum="md5:11111111111111111111111111111111",
        ),
        DirectMirror(
            mirror_id="terabox-mirror",
            host_kind="terabox",
            share_url="https://terabox.com/s/example",
            size_bytes=100,
        ),
    ]
    if reverse:
        mirrors.reverse()
    return DirectResolveResponse(
        protocol_version="direct-download-provider/v1",
        request_id="00000000-0000-0000-0000-000000000001",
        artifacts=[
            DirectArtifact(
                artifact_id="provider-artifact-1",
                coverage=DirectArtifactCoverage(issue_numbers=["1"]),
                route=DirectArtifactRoute.DIRECT_ARTIFACT,
                format="cbz",
                quality="digital",
                size_bytes=100,
                mirrors=mirrors,
            )
        ],
    )


def _generic_response() -> DirectResolveResponse:
    return DirectResolveResponse(
        protocol_version="direct-download-provider/v1",
        request_id="00000000-0000-0000-0000-000000000001",
        artifacts=[
            DirectArtifact(
                artifact_id="provider-artifact-1",
                coverage=DirectArtifactCoverage(issue_numbers=["1"]),
                route=DirectArtifactRoute.DIRECT_ARTIFACT,
                format="cbz",
                quality="digital",
                size_bytes=100,
                mirrors=[
                    DirectMirror(
                        mirror_id="generic-mirror",
                        host_kind="generic_https",
                        final_url="https://files.example.test/signed.cbz?token=hidden",
                        size_bytes=100,
                    )
                ],
            )
        ],
    )


class _ResolveClient:
    def __init__(self, response: DirectResolveResponse) -> None:
        self.response = response
        self.requests: list[Any] = []
        self.closed = False

    async def resolve(self, request: Any) -> DirectResolveResponse:
        self.requests.append(request)
        return self.response.model_copy(update={"request_id": request.request_id})

    async def aclose(self) -> None:
        self.closed = True


class _FallbackResolveClient(_ResolveClient):
    async def resolve(self, request: Any) -> DirectResolveResponse:
        self.requests.append(request)
        profile = request.resolver_profile
        if profile is None:
            raise DirectProviderClientError(
                "browser_challenge_required",
                "Browser challenge required.",
                retryable=True,
            )
        if profile.endpoint == "http://flaresolverr:8191":
            raise DirectProviderClientError(
                "resolver_timed_out",
                "Resolver timed out.",
                retryable=True,
            )
        return self.response.model_copy(update={"request_id": request.request_id})


@pytest.mark.asyncio
async def test_planning_selects_best_eligible_route_and_persists_no_urls(
    session: AsyncSession,
) -> None:
    client = _ResolveClient(_response())

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: client,
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.attempt.state is DirectAcquisitionState.PLANNED
    assert result.selected_artifact.host_kind is DirectArtifactHostKind.PIXELDRAIN
    assert result.selected_artifact.state is DirectArtifactState.PLANNED
    assert result.selected_artifact.is_selected is True
    assert result.plan.complete is True
    assert result.plan.pinned_route_applied is False
    rendered = repr(result.attempt.plan_snapshot)
    assert "https://" not in rendered
    assert "signed.cbz" not in rendered
    assert "token" not in rendered.casefold()
    assert "pixel-mirror" in rendered
    assert client.closed is True


@pytest.mark.asyncio
async def test_planning_ignores_retired_hosts_when_viable_mirrors_remain(
    session: AsyncSession,
) -> None:
    response = _response()
    response.artifacts[0].mirrors.extend(
        [
            DirectMirror(
                mirror_id="zippyshare-mirror",
                host_kind="generic_https",
                final_url="https://www12.zippyshare.com/v/example/file.html",
            ),
            DirectMirror(
                mirror_id="dropapk-mirror",
                host_kind="generic_https",
                final_url="https://dropapk.to/example",
            ),
        ]
    )

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: _ResolveClient(response),
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.selected_artifact.host_kind is DirectArtifactHostKind.PIXELDRAIN
    rendered = repr(result.attempt.plan_snapshot)
    assert "zippyshare-mirror" not in rendered
    assert "dropapk-mirror" not in rendered


@pytest.mark.asyncio
async def test_generic_only_provider_does_not_require_visible_host_setting(
    session: AsyncSession,
) -> None:
    provider = await session.get(DirectProviderConfig, 1)
    assert provider is not None
    provider.provider_id = "pullbox.annas_archive"
    provider.manifest_snapshot = {
        "protocol_version": "direct-download-provider/v1",
        "provider_id": "pullbox.annas_archive",
        "display_name": "Anna's Archive",
        "description": "A direct provider fixture.",
        "provider_version": "1.0.0",
        "supported_protocol_versions": ["direct-download-provider/v1"],
        "publisher": "Pullbox",
        "license": "GPL-3.0-or-later",
        "source_domains": ["annas-archive.gd"],
        "artifact_host_patterns": ["generic_https"],
        "capabilities": {"search": True, "resolve": True},
        "configuration_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }
    generic = (
        await session.execute(
            select(DirectHostConfig).where(
                DirectHostConfig.host_kind == DirectArtifactHostKind.GENERIC_HTTPS
            )
        )
    ).scalar_one()
    generic.enabled = False
    await session.flush()

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: _ResolveClient(_generic_response()),
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.selected_artifact.host_kind is DirectArtifactHostKind.GENERIC_HTTPS
    assert result.plan.complete is True


@pytest.mark.asyncio
async def test_planning_resolve_tries_ordinary_http_then_ranked_resolvers(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pullbox.services import direct_resolver_service

    provider = await session.get(DirectProviderConfig, 1)
    assert provider is not None
    provider.resolver_enabled = True
    options = (
        ProviderResolverOption(
            resolver_id=1,
            resolver_name="FlareSolverr",
            resolver_kind=DirectResolverKind.FLARESOLVERR,
            profile=DirectResolverProfile(
                endpoint="http://flaresolverr:8191",
                timeout_seconds=60,
                max_concurrency=1,
                declared_domains=["getcomics.org"],
            ),
        ),
        ProviderResolverOption(
            resolver_id=2,
            resolver_name="Byparr",
            resolver_kind=DirectResolverKind.BYPARR,
            profile=DirectResolverProfile(
                endpoint="http://byparr:8191",
                timeout_seconds=60,
                max_concurrency=1,
                declared_domains=["getcomics.org"],
            ),
        ),
    )

    async def profiles(*_args: object) -> tuple[ProviderResolverOption, ...]:
        return options

    monkeypatch.setattr(direct_resolver_service, "build_provider_resolver_profiles", profiles)
    client = _FallbackResolveClient(_response())

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: client,
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.attempt.state is DirectAcquisitionState.PLANNED
    assert [
        request.resolver_profile.endpoint if request.resolver_profile else None
        for request in client.requests
    ] == [None, "http://flaresolverr:8191", "http://byparr:8191"]


@pytest.mark.asyncio
async def test_planning_skips_only_the_blocklisted_artifact_route(
    session: AsyncSession,
) -> None:
    blocked_route = direct_route_identity(
        "community.getcomics",
        "candidate-1",
        "provider-artifact-1",
        "pixel-mirror",
    )
    await BlocklistService.add_direct_artifact_entry(
        session,
        "Planner Series 001 (2026)",
        route_identity=blocked_route,
        artifact_host="PixelDrain",
        issue_id=1,
        series_id=1,
        error_message="The PixelDrain artifact is unavailable.",
    )

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: _ResolveClient(_response()),
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.selected_artifact.host_kind is DirectArtifactHostKind.GENERIC_HTTPS
    blocked_snapshot = next(
        route
        for route in result.attempt.plan_snapshot["artifacts"]
        if route["artifact_identity"] == blocked_route
    )
    assert blocked_snapshot["eligible"] is False
    assert blocked_snapshot["eligibility_code"] == "route_blocklisted"


@pytest.mark.asyncio
async def test_planning_accepts_only_pre_plan_semantic_review_intervention(
    session: AsyncSession,
) -> None:
    attempt = await session.get(DirectAcquisitionAttempt, 1)
    assert attempt is not None
    attempt.state = DirectAcquisitionState.INTERVENTION
    attempt.failure_class = DirectArtifactFailureClass.USER_ACTION
    attempt.failure_code = "semantic_review_required"
    attempt.error_message = "Review this direct result before downloading."
    await session.flush()

    result = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: _ResolveClient(_response()),
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert result.attempt.state is DirectAcquisitionState.PLANNED
    assert result.attempt.failure_class is None
    assert result.attempt.failure_code is None
    assert result.attempt.error_message is None


@pytest.mark.asyncio
async def test_planning_rejects_non_semantic_intervention(
    session: AsyncSession,
) -> None:
    attempt = await session.get(DirectAcquisitionAttempt, 1)
    assert attempt is not None
    attempt.state = DirectAcquisitionState.INTERVENTION
    attempt.failure_code = "artifact_host_auth_required"
    await session.flush()

    with pytest.raises(DirectAcquisitionPlanningError) as error:
        await plan_direct_acquisition(
            session,
            acquisition_id=1,
            provider_client_factory=lambda **_kwargs: _ResolveClient(_response()),
            provider_secret_loader=lambda _config: _provider_material(),
            now=lambda: NOW,
        )

    assert error.value.code == "acquisition_not_discovered"


@pytest.mark.asyncio
async def test_planning_is_deterministic_and_manual_pin_cannot_select_ineligible_route(
    session: AsyncSession,
) -> None:
    first = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: _ResolveClient(_response(reverse=True)),
        provider_secret_loader=lambda _config: _provider_material(),
        pinned_route_identity=direct_route_identity(
            "community.getcomics",
            "candidate-1",
            "provider-artifact-1",
            "terabox-mirror",
        ),
        now=lambda: NOW,
    )

    assert first.selected_artifact.host_kind is DirectArtifactHostKind.PIXELDRAIN
    assert first.plan.explanation_code == "pinned_route_ineligible"
    assert first.plan.pinned_route_applied is False


@pytest.mark.asyncio
async def test_planning_fails_closed_when_provider_host_claim_disagrees_with_url(
    session: AsyncSession,
) -> None:
    response = _response()
    response.artifacts[0].mirrors[0] = DirectMirror(
        mirror_id="mismatch",
        host_kind="pixeldrain",
        share_url="https://mega.nz/file/example#secret",
    )

    with pytest.raises(DirectAcquisitionPlanningError, match="host identity") as error:
        await plan_direct_acquisition(
            session,
            acquisition_id=1,
            provider_client_factory=lambda **_kwargs: _ResolveClient(response),
            provider_secret_loader=lambda _config: _provider_material(),
            now=lambda: NOW,
        )

    assert error.value.code == "provider_host_kind_mismatch"
    attempt = await session.get(DirectAcquisitionAttempt, 1)
    assert attempt is not None
    assert "mega.nz" not in repr(attempt.progress_snapshot)


@pytest.mark.asyncio
async def test_source_reresolution_uses_only_stable_snapshot_ids(
    session: AsyncSession,
) -> None:
    client = _ResolveClient(_response())
    planned = await plan_direct_acquisition(
        session,
        acquisition_id=1,
        provider_client_factory=lambda **_kwargs: client,
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    refreshed = _ResolveClient(_response())
    request = await resolve_planned_artifact_source(
        session,
        acquisition_id=1,
        artifact_id=planned.selected_artifact.id,
        provider_client_factory=lambda **_kwargs: refreshed,
        provider_secret_loader=lambda _config: _provider_material(),
        now=lambda: NOW,
    )

    assert request.host_kind is DirectArtifactHostKind.PIXELDRAIN
    assert request.share_url == "https://pixeldrain.com/u/abc123"
    assert request.final_url is None
    assert request.checksum == "md5:11111111111111111111111111111111"
    assert "signed.cbz" not in repr(request)
    assert refreshed.closed is True


def _provider_material() -> Any:
    class _Material:
        bearer_token = "x" * 32
        configuration: ClassVar[dict[str, str]] = {}

        def __repr__(self) -> str:
            return "_Material(<redacted>)"

    return _Material()
