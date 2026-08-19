"""Tests for intervention queue/history context loading."""

from __future__ import annotations

import pytest

from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.series import Series, SeriesStatus, SeriesType


async def _seed_intervention_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    series = Series(
        comicvine_id=99100,
        title="Batman",
        sort_title="Batman",
        year_start=2016,
        status=SeriesStatus.CONTINUING,
        series_type=SeriesType.STANDARD,
        monitored=True,
        issue_count=2,
    )
    db_session.add(series)
    await db_session.flush()

    issue = Issue(
        series_id=series.id,
        comicvine_id=88100,
        issue_number=1.0,
        title="Issue #1",
        status=IssueStatus.WANTED,
        issue_type=IssueType.ISSUE,
    )
    db_session.add(issue)
    await db_session.flush()

    db_session.add_all(
        [
            PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 (2016) [Digital].cbz",
                download_url="https://indexer.example.com/pending-high",
                is_torrent=True,
                file_size=100_000_000,
                confidence="high",
                match_details={
                    "series_match_type": "fuzzy",
                    "issue_match": False,
                    "year_match": True,
                    "type_match": True,
                    "indexer_name": "Torrent Cave",
                    "series_similarity": 0.91,
                },
                status=PendingMatchStatus.PENDING,
            ),
            PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 Direct recovery.cbz",
                download_url="pullbox-direct://attempt/991",
                is_torrent=False,
                confidence="high",
                match_details={
                    "source_kind": "direct",
                    "provider_name": "pullbox.getcomics",
                    "artifact_host_kind": "terabox",
                    "failure_class": "artifact_host_auth_required",
                    "failure_code": "artifact_host_auth_required",
                    "series_match_type": "exact",
                },
                status=PendingMatchStatus.PENDING,
            ),
            PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 Alternate.cbz",
                download_url="https://indexer.example.com/pending-low",
                is_torrent=False,
                file_size=90_000_000,
                confidence="low",
                match_details={
                    "series_match_type": "exact",
                    "issue_match": True,
                    "year_match": True,
                    "type_match": True,
                    "indexer_name": "NZB Cave",
                },
                status=PendingMatchStatus.PENDING,
            ),
            PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 Rejected.cbz",
                download_url="https://indexer.example.com/rejected",
                is_torrent=False,
                file_size=95_000_000,
                confidence="medium",
                match_details={
                    "series_match_type": "exact",
                    "issue_match": True,
                    "year_match": True,
                    "type_match": True,
                    "indexer_name": "NZB Cave",
                    "rejection_reason": "Wrong release",
                },
                status=PendingMatchStatus.REJECTED,
            ),
        ]
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_load_intervention_context_filters_queue_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.intervention_context_loaders import load_intervention_context

    await _seed_intervention_rows(db_session)

    context = await load_intervention_context(
        db_session,
        tab="queue",
        reason_filter="issue_mismatch",
        confidence_filter="high",
        protocol_filter="torrent",
        search_query="Batman",
        requested_page=99,
    )

    assert context["tab"] == "queue"
    assert context["queue_count"] == 3
    assert context["pending_count"] == 3
    assert context["history_total"] == 1
    assert context["filtered_count"] == 1
    assert context["visible_count"] == 1
    assert context["page"] == 1
    assert context["total_pages"] == 1
    assert context["has_filters"] is True
    assert context["reason_filter"] == "issue_mismatch"
    assert context["confidence_filter"] == "high"
    assert context["protocol_filter"] == "torrent"
    assert context["search_query"] == "Batman"
    assert context["high_count"] == 1
    assert context["low_count"] == 1
    [pending_match] = context["pending_matches"]
    assert pending_match.release_title == "Batman 001 (2016) [Digital].cbz"
    assert context["intervention_item_meta"][pending_match.id]["source_label"] == "Torrent Cave"


@pytest.mark.asyncio
async def test_load_intervention_context_separates_acquisition_recovery_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    """Direct download failures appear in recovery, not semantic match review."""
    from pullbox.ui.intervention_context_loaders import load_intervention_context

    await _seed_intervention_rows(db_session)

    review = await load_intervention_context(db_session, tab="queue")
    recovery = await load_intervention_context(db_session, tab="recovery")

    assert review["match_review_count"] == 2
    assert review["recovery_count"] == 1
    assert [item.release_title for item in review["pending_matches"]] == [
        "Batman 001 Alternate.cbz",
        "Batman 001 (2016) [Digital].cbz",
    ]
    assert recovery["tab"] == "recovery"
    assert [item.release_title for item in recovery["pending_matches"]] == [
        "Batman 001 Direct recovery.cbz"
    ]


@pytest.mark.asyncio
async def test_load_intervention_context_filters_history_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.intervention_context_loaders import load_intervention_context

    await _seed_intervention_rows(db_session)

    context = await load_intervention_context(
        db_session,
        tab="history",
        outcome_filter="rejected",
        confidence_filter="medium",
        protocol_filter="usenet",
        search_query="Rejected",
        sort="title",
        requested_page=1,
    )

    assert context["tab"] == "history"
    assert context["queue_count"] == 3
    assert context["history_total"] == 1
    assert context["history_rejected_count"] == 1
    assert context["history_approved_count"] == 0
    assert context["history_expired_count"] == 0
    assert context["has_filters"] is True
    assert context["outcome_filter"] == "rejected"
    assert context["confidence_filter"] == "medium"
    assert context["protocol_filter"] == "usenet"
    assert context["sort"] == "title"
    [history_item] = context["history_items"]
    assert history_item.release_title == "Batman 001 Rejected.cbz"
    assert context["intervention_item_meta"][history_item.id]["rejection_reason"] == "Wrong release"
