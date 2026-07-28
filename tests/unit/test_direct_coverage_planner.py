"""Coverage-aware deterministic planning for direct-download candidates."""

from __future__ import annotations

import random

import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectHostAccountState,
)
from pullbox.services.direct_coverage_planner import (
    DirectArtifactOption,
    DirectRouteOption,
    plan_direct_coverage,
)


def _route(
    identity: str,
    *,
    host: DirectArtifactHostKind = DirectArtifactHostKind.GENERIC_HTTPS,
    transport_rank: int = 0,
    host_preference: int = 50,
    eligible: bool = True,
    account_state: DirectHostAccountState = DirectHostAccountState.NOT_CONFIGURED,
    resolver_required: bool = False,
) -> DirectRouteOption:
    return DirectRouteOption(
        route_identity=identity,
        route_kind=DirectArtifactRouteKind.DIRECT,
        host_kind=host,
        transport_rank=transport_rank,
        eligible=eligible,
        eligibility_code="eligible" if eligible else "authentication_required",
        host_preference=host_preference,
        account_state=account_state,
        quota_remaining=None,
        resumable=True,
        resolver_required=resolver_required,
    )


def _artifact(
    identity: str,
    coverage: set[str],
    *,
    semantic_rank: int = 0,
    quality_rank: int = 0,
    expected_size: int = 100,
    provider_confidence: float = 1.0,
    provider_priority: int = 10,
    routes: tuple[DirectRouteOption, ...] | None = None,
) -> DirectArtifactOption:
    return DirectArtifactOption(
        provider_identity="pullbox.getcomics",
        provider_candidate_id=f"candidate-{identity}",
        artifact_identity=identity,
        coverage=frozenset(coverage),
        semantic_rank=semantic_rank,
        quality_rank=quality_rank,
        expected_size=expected_size,
        provider_confidence=provider_confidence,
        provider_priority=provider_priority,
        routes=routes or (_route(f"route-{identity}"),),
    )


def test_planner_is_deterministic_under_shuffled_provider_completion() -> None:
    artifacts = [
        _artifact("single-1", {"1"}),
        _artifact("single-2", {"2"}),
        _artifact("pack", {"1", "2"}),
    ]
    shuffled = artifacts.copy()
    random.Random(20260728).shuffle(shuffled)

    expected = plan_direct_coverage(frozenset({"1", "2"}), artifacts)
    actual = plan_direct_coverage(frozenset({"1", "2"}), shuffled)

    assert actual == expected
    assert [item.artifact_identity for item in actual.selected] == ["pack"]
    assert actual.uncovered == frozenset()


def test_semantic_correctness_outranks_a_more_convenient_pack() -> None:
    plan = plan_direct_coverage(
        frozenset({"1", "2"}),
        [
            _artifact("wrong-title-pack", {"1", "2"}, semantic_rank=2),
            _artifact("exact-1", {"1"}, semantic_rank=0),
            _artifact("exact-2", {"2"}, semantic_rank=0),
        ],
    )

    assert [item.artifact_identity for item in plan.selected] == ["exact-1", "exact-2"]
    assert plan.explanation_code == "complete_coverage"


def test_quality_preference_precedes_smallest_artifact_count() -> None:
    plan = plan_direct_coverage(
        frozenset({"1", "2"}),
        [
            _artifact("lower-quality-pack", {"1", "2"}, quality_rank=2),
            _artifact("preferred-1", {"1"}, quality_rank=0),
            _artifact("preferred-2", {"2"}, quality_rank=0),
        ],
    )

    assert [item.artifact_identity for item in plan.selected] == [
        "preferred-1",
        "preferred-2",
    ]


def test_route_ranking_is_content_independent_and_keeps_fallbacks() -> None:
    artifact = _artifact(
        "issue-1",
        {"1"},
        routes=(
            _route(
                "resolver",
                host=DirectArtifactHostKind.TERABOX,
                transport_rank=3,
                account_state=DirectHostAccountState.HEALTHY,
                resolver_required=True,
            ),
            _route(
                "native",
                host=DirectArtifactHostKind.PIXELDRAIN,
                transport_rank=1,
                account_state=DirectHostAccountState.HEALTHY,
            ),
            _route("final-https", transport_rank=0),
        ),
    )

    plan = plan_direct_coverage(frozenset({"1"}), [artifact])

    assert [route.route_identity for route in plan.selected[0].ordered_routes] == [
        "final-https",
        "native",
        "resolver",
    ]
    assert plan.selected[0].selected_route_identity == "final-https"


def test_explicit_host_preference_precedes_default_transport_tier() -> None:
    artifact = _artifact(
        "issue-1",
        {"1"},
        routes=(
            _route(
                "generic",
                transport_rank=0,
                host_preference=70,
            ),
            _route(
                "pixel",
                host=DirectArtifactHostKind.PIXELDRAIN,
                transport_rank=1,
                host_preference=10,
                account_state=DirectHostAccountState.HEALTHY,
            ),
        ),
    )

    plan = plan_direct_coverage(frozenset({"1"}), [artifact])

    assert [route.route_identity for route in plan.selected[0].ordered_routes] == [
        "pixel",
        "generic",
    ]
    assert plan.selected[0].selected_route_identity == "pixel"


def test_manual_mirror_pin_is_scoped_to_this_plan_and_cannot_bypass_safety() -> None:
    artifact = _artifact(
        "issue-1",
        {"1"},
        routes=(
            _route("automatic", transport_rank=0),
            _route("manual", transport_rank=1),
            _route("blocked", transport_rank=2, eligible=False),
        ),
    )

    pinned = plan_direct_coverage(
        frozenset({"1"}),
        [artifact],
        pinned_route_identity="manual",
    )
    blocked = plan_direct_coverage(
        frozenset({"1"}),
        [artifact],
        pinned_route_identity="blocked",
    )
    automatic = plan_direct_coverage(frozenset({"1"}), [artifact])

    assert pinned.selected[0].selected_route_identity == "manual"
    assert pinned.pinned_route_applied is True
    assert blocked.selected[0].selected_route_identity == "automatic"
    assert blocked.pinned_route_applied is False
    assert blocked.explanation_code == "pinned_route_ineligible"
    assert automatic.selected[0].selected_route_identity == "automatic"


def test_incomplete_coverage_is_explicit_and_chooses_best_safe_partial_plan() -> None:
    plan = plan_direct_coverage(
        frozenset({"1", "2", "annual-1"}),
        [
            _artifact("issues", {"1", "2"}),
            _artifact(
                "blocked-annual",
                {"annual-1"},
                routes=(_route("blocked", eligible=False),),
            ),
        ],
    )

    assert [item.artifact_identity for item in plan.selected] == ["issues"]
    assert plan.uncovered == frozenset({"annual-1"})
    assert plan.complete is False
    assert plan.explanation_code == "incomplete_coverage"


@pytest.mark.parametrize(
    ("requested", "artifacts", "expected"),
    [
        (
            {"1"},
            [_artifact("issue-1", {"1"})],
            ["issue-1"],
        ),
        (
            {"annual-1"},
            [_artifact("annual-1", {"annual-1"})],
            ["annual-1"],
        ),
        (
            {"special-holiday"},
            [_artifact("holiday-special", {"special-holiday"})],
            ["holiday-special"],
        ),
        (
            {"1", "2", "3", "4"},
            [
                _artifact("range-1-4", {"1", "2", "3", "4"}),
                _artifact("single-1", {"1"}),
                _artifact("single-2", {"2"}),
                _artifact("single-3", {"3"}),
                _artifact("single-4", {"4"}),
            ],
            ["range-1-4"],
        ),
        (
            {"volume-1"},
            [_artifact("volume-1", {"volume-1"})],
            ["volume-1"],
        ),
        (
            {"1", "2", "3", "4", "5", "6"},
            [
                _artifact("omnibus", {"1", "2", "3", "4", "5", "6"}),
                _artifact("volume-a", {"1", "2", "3"}),
                _artifact("volume-b", {"4", "5", "6"}),
            ],
            ["omnibus"],
        ),
        (
            {"1", "2", "3", "4"},
            [
                _artifact("overlap-a", {"1", "2", "3"}),
                _artifact("overlap-b", {"2", "3", "4"}),
                _artifact("single-4", {"4"}),
            ],
            ["overlap-a", "overlap-b"],
        ),
    ],
)
def test_planner_coverage_matrix(
    requested: set[str],
    artifacts: list[DirectArtifactOption],
    expected: list[str],
) -> None:
    plan = plan_direct_coverage(frozenset(requested), artifacts)

    assert [item.artifact_identity for item in plan.selected] == expected
    assert plan.complete is True
    assert plan.uncovered == frozenset()


def test_planner_snapshot_is_stable_across_many_completion_orders() -> None:
    artifacts = [
        _artifact("single-1", {"1"}, expected_size=75),
        _artifact("single-2", {"2"}, expected_size=75),
        _artifact("single-3", {"3"}, expected_size=75),
        _artifact("range-1-2", {"1", "2"}, expected_size=130),
        _artifact("range-2-3", {"2", "3"}, expected_size=130),
        _artifact("complete", {"1", "2", "3"}, expected_size=180),
    ]
    expected = plan_direct_coverage(frozenset({"1", "2", "3"}), artifacts)

    for seed in range(100):
        shuffled = artifacts.copy()
        random.Random(seed).shuffle(shuffled)
        assert plan_direct_coverage(frozenset({"1", "2", "3"}), shuffled) == expected
