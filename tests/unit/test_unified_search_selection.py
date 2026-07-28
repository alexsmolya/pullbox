"""Source-neutral winner selection for indexer and direct results."""

from __future__ import annotations

from pullbox.models.issue import IssueType
from pullbox.providers.base import ReleaseResult
from pullbox.providers.direct.contract import DirectCandidate, DirectParsedCandidate
from pullbox.services.direct_search_coordinator import (
    DirectSearchOutcome,
    DirectSearchProvider,
    DirectValidatedCandidate,
)
from pullbox.services.release_validator import ReleaseValidator
from pullbox.services.search_source_selection import select_search_source
from pullbox.services.search_targets import IssueSearchOutcome, IssueSearchTarget


def _release(title: str, source: str, *, size: int = 100_000_000) -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name=source,
        download_url=f"https://example.test/{source}/{title}",
        size_bytes=size,
        age_days=1,
        seeders=10,
        leechers=1,
        grabs=None,
        is_torrent=True,
        category="7030",
        published_at=None,
    )


def _validation(release: ReleaseResult):  # type: ignore[no-untyped-def]
    matched, _ = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Batman",
        wanted_issue=1,
        wanted_year=2016,
    )
    return matched[0]


def _direct_result(release: ReleaseResult) -> DirectValidatedCandidate:
    return DirectValidatedCandidate(
        provider=DirectSearchProvider(
            provider_config_id=7,
            provider_identity="pullbox.getcomics",
            display_name="GetComics",
            endpoint="http://provider:8780",
            bearer_token="provider-token-with-enough-length",
            provider_priority=10,
        ),
        candidate=DirectCandidate(
            provider_candidate_id="candidate-1",
            source_reference="https://getcomics.org/post",
            display_title=release.title,
            raw_title=release.title,
            parsed=DirectParsedCandidate(
                series_title="Batman",
                issue_numbers=["1"],
                year=2016,
                format="cbz",
                quality="digital",
            ),
            provider_confidence=0.98,
        ),
        release=release,
        validation=_validation(release),
    )


def _outcome(
    indexer_release: ReleaseResult,
    direct_result: DirectValidatedCandidate,
) -> IssueSearchOutcome:
    validation = _validation(indexer_release)
    target = IssueSearchTarget(
        issue_id=1,
        series_id=2,
        series_title="Batman",
        issue_number=1,
        issue_type=IssueType.ISSUE,
        series_year=2016,
    )
    return IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=1,
        raw_results=[indexer_release],
        filtered_results=[indexer_release],
        matched=[validation],
        rejected=[],
        best_release=indexer_release,
        best_validation=validation,
        search_details={},
        elapsed_ms=1,
        direct_outcome=DirectSearchOutcome(
            matched=(direct_result,),
            rejected=(),
            failures=(),
            providers_searched=1,
            elapsed_ms=1,
        ),
    )


def test_direct_candidate_can_win_using_existing_search_score() -> None:
    indexer = _release("Batman 001.cbz", "Indexer", size=25_000_000)
    direct = _direct_result(_release("Batman 001 (2016) (Digital).cbz", "GetComics"))

    selected = select_search_source(_outcome(indexer, direct), {})

    assert selected is not None
    assert selected.source_kind == "direct"
    assert selected.direct_result is direct
    assert selected.validation is direct.validation


def test_equal_score_preserves_existing_indexer_precedence() -> None:
    indexer = _release("Batman 001 (2016) (Digital).cbz", "Indexer")
    direct = _direct_result(_release("Batman 001 (2016) (Digital).cbz", "GetComics"))

    selected = select_search_source(_outcome(indexer, direct), {})

    assert selected is not None
    assert selected.source_kind == "indexer"
    assert selected.release is indexer
    assert selected.direct_result is None


def test_equal_score_respects_direct_first_source_priority() -> None:
    indexer = _release("Batman 001 (2016) (Digital).cbz", "Indexer")
    direct = _direct_result(_release("Batman 001 (2016) (Digital).cbz", "GetComics"))

    selected = select_search_source(
        _outcome(indexer, direct),
        {},
        source_priority=["direct", "torrent", "usenet"],
    )

    assert selected is not None
    assert selected.source_kind == "direct"
    assert selected.direct_result is direct
