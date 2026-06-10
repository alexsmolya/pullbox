"""Unit tests for MatchingService using the shared semantic core."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from pullbox.core.events import EventBus
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series, SeriesType
from pullbox.services.matching_service import MatchingService

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
