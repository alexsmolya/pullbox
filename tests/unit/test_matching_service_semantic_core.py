"""Unit tests for MatchingService using the shared semantic core."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from pullbox.core.events import EventBus, FileMatched
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.matching_suggestion import MatchingSuggestion, SuggestionStatus
from pullbox.models.series import Series, SeriesType
from pullbox.services.matching_service import (
    MatchingService,
    _confidence_from_match,
    _extract_comicvine_id,
    _year_close,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def _write_cbz(path: Path, comicinfo_xml: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if comicinfo_xml is not None:
            zf.writestr("ComicInfo.xml", comicinfo_xml)
        zf.writestr("page001.jpg", b"fake")


async def _create_root(db_session: AsyncSession, tmp_path: Path) -> LibraryRoot:
    root = LibraryRoot(name="Main", path=str(tmp_path / "library"))
    db_session.add(root)
    await db_session.flush()
    return root


async def _create_series_with_issue(
    db_session: AsyncSession,
    *,
    title: str = "Batman",
    year: int = 2016,
    issue_number: float = 1.0,
    issue_type: IssueType = IssueType.ISSUE,
) -> Issue:
    series = Series(
        title=title,
        sort_title=title.lower(),
        year_start=year,
        series_type=(SeriesType.ANNUAL if issue_type == IssueType.ANNUAL else SeriesType.STANDARD),
    )
    db_session.add(series)
    await db_session.flush()

    issue = Issue(
        series_id=series.id,
        issue_number=issue_number,
        issue_type=issue_type,
        status=IssueStatus.WANTED,
        title=f"Issue {issue_number}",
    )
    db_session.add(issue)
    await db_session.flush()
    return issue


class TestMatchingServiceSharedSemanticCore:
    """The local library matcher should use the shared semantic engine."""

    @pytest.mark.asyncio
    async def test_standard_issue_filename_matches_issue(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        issue = await _create_series_with_issue(db_session)
        root = await _create_root(db_session, tmp_path)
        file_path = tmp_path / "Batman 001.cbz"
        file_path.touch()

        library_file = LibraryFile(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=1024,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            library_root_id=root.id,
        )
        db_session.add(library_file)
        await db_session.flush()

        service = MatchingService(EventBus())
        confidence = await service.match_file(db_session, library_file)

        assert confidence in (MatchConfidence.HIGH, MatchConfidence.MEDIUM)
        assert library_file.issue_id == issue.id
        assert library_file.parsed_series == "Batman"
        assert library_file.parsed_issue_number == 1.0

    @pytest.mark.asyncio
    async def test_comicinfo_issue_id_direct_match_is_high(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        issue = await _create_series_with_issue(db_session)
        issue.comicvine_id = 987654
        await db_session.flush()
        root = await _create_root(db_session, tmp_path)
        file_path = tmp_path / "Batman 999.cbz"
        _write_cbz(
            file_path,
            """<?xml version="1.0"?>
            <ComicInfo>
              <Series>Batman</Series>
              <Number>999</Number>
              <Volume>2016</Volume>
              <Web>https://comicvine.gamespot.com/batman-1/4000-987654/</Web>
            </ComicInfo>
            """,
        )

        library_file = LibraryFile(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=2048,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            library_root_id=root.id,
        )
        db_session.add(library_file)
        await db_session.flush()

        service = MatchingService(EventBus())
        confidence = await service.match_file(db_session, library_file)

        assert confidence == MatchConfidence.HIGH
        assert library_file.issue_id == issue.id
        assert library_file.has_comicinfo is True

    @pytest.mark.asyncio
    async def test_comicinfo_series_only_match_is_reviewable_medium(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        await _create_series_with_issue(db_session, title="Gotham Gazette", year=2025)
        root = await _create_root(db_session, tmp_path)
        file_path = tmp_path / "Gotham Gazette Special.cbz"
        _write_cbz(
            file_path,
            """<?xml version="1.0"?>
            <ComicInfo>
              <Series>Gotham Gazette</Series>
              <Volume>2025</Volume>
            </ComicInfo>
            """,
        )

        library_file = LibraryFile(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=2048,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            library_root_id=root.id,
        )
        db_session.add(library_file)
        await db_session.flush()

        service = MatchingService(EventBus())
        confidence = await service.match_file(db_session, library_file)

        assert confidence == MatchConfidence.MEDIUM
        assert library_file.issue_id is None
        assert library_file.parsed_series == "Gotham Gazette"
        assert library_file.has_comicinfo is True

    @pytest.mark.asyncio
    async def test_manual_match_and_unmatch_update_file_and_emit_event(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        issue = await _create_series_with_issue(db_session, title="Nightwing", year=2024)
        root = await _create_root(db_session, tmp_path)
        file_path = tmp_path / "Nightwing 001.cbz"
        file_path.touch()
        library_file = LibraryFile(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=1024,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            library_root_id=root.id,
        )
        db_session.add(library_file)
        await db_session.flush()
        captured: list[FileMatched] = []
        event_bus = EventBus()
        event_bus.subscribe(FileMatched, captured.append)
        service = MatchingService(event_bus)

        matched = await service.manual_match(db_session, library_file.id, issue.id)

        assert matched.issue_id == issue.id
        assert matched.match_confidence == MatchConfidence.MANUAL
        assert captured == [
            FileMatched(
                library_file_id=library_file.id,
                issue_id=issue.id,
                confidence=MatchConfidence.MANUAL,
            )
        ]

        unmatched = await service.unmatch_file(db_session, library_file.id)

        assert unmatched.issue_id is None
        assert unmatched.match_confidence == MatchConfidence.UNMATCHED

    @pytest.mark.asyncio
    async def test_variant_suggestion_uses_parent_series_and_avoids_duplicates(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        parent_issue = await _create_series_with_issue(db_session, title="Batman", year=2024)
        root = await _create_root(db_session, tmp_path)
        file_path = tmp_path / "Batman Omnibus.cbz"
        file_path.touch()
        library_file = LibraryFile(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=1024,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            library_root_id=root.id,
        )
        db_session.add(library_file)
        await db_session.flush()
        parsed_release = SimpleNamespace(
            series_name="Batman Omnibus",
            year=2025,
            issue_type=SimpleNamespace(value="omnibus"),
        )
        service = MatchingService(EventBus())

        await service._create_suggestion_if_variant(db_session, library_file, parsed_release)
        await service._create_suggestion_if_variant(db_session, library_file, parsed_release)

        suggestions = (
            (await db_session.execute(select(MatchingSuggestion).order_by(MatchingSuggestion.id)))
            .scalars()
            .all()
        )
        assert len(suggestions) == 1
        [suggestion] = suggestions
        assert suggestion.library_file_id == library_file.id
        assert suggestion.parent_series_id == parent_issue.series_id
        assert suggestion.suggested_title == "Batman Omnibus"
        assert suggestion.suggested_year == 2025
        assert suggestion.suggested_series_type == "omnibus"
        assert suggestion.status == SuggestionStatus.PENDING


def test_matching_helper_extracts_comicvine_issue_ids() -> None:
    assert _extract_comicvine_id("https://comicvine.gamespot.com/batman-1/4000-123456/") == 123456
    assert _extract_comicvine_id("https://comicvine.gamespot.com/batman/4050-111/") == 111
    assert _extract_comicvine_id("https://example.test/not-comicvine") is None
    assert _extract_comicvine_id(None) is None


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (2025, 2025, True),
        (2025, 2024, True),
        (2025, 2023, False),
        (None, 2025, False),
        (2025, None, False),
    ],
)
def test_matching_helper_year_close_uses_one_year_tolerance(
    left: int | None,
    right: int | None,
    expected: bool,
) -> None:
    assert _year_close(left, right) is expected


@pytest.mark.parametrize(
    ("match_type", "similarity", "parsed_year", "series_year", "expected"),
    [
        ("exact", 1.0, 2025, 2025, MatchConfidence.HIGH),
        ("exact", 1.0, 2025, 2020, MatchConfidence.MEDIUM),
        ("alternate", 0.95, 2025, 2024, MatchConfidence.HIGH),
        ("token_set", 0.8, None, None, MatchConfidence.MEDIUM),
        ("fuzzy", 0.9, 2025, 2025, MatchConfidence.MEDIUM),
        ("fuzzy", 0.9, 2025, 2020, MatchConfidence.LOW),
        ("weak", 0.7, 2025, 2025, MatchConfidence.LOW),
    ],
)
def test_matching_helper_confidence_buckets(
    match_type: str,
    similarity: float,
    parsed_year: int | None,
    series_year: int | None,
    expected: MatchConfidence,
) -> None:
    assert _confidence_from_match(match_type, similarity, parsed_year, series_year) == expected
