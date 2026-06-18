"""Direct route-function coverage for matching suggestion API contracts."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pullbox.api.v1 import suggestions as suggestions_api
from pullbox.core.exceptions import NotFoundError, ValidationError
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.matching_suggestion import MatchingSuggestion, SuggestionStatus
from pullbox.models.series import Series
from pullbox.schemas.suggestion import SuggestionAccept

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["conftest_security"]


async def _seed_suggestion_graph(
    session: AsyncSession,
    *,
    status: SuggestionStatus = SuggestionStatus.PENDING,
    index: int = 1,
) -> tuple[MatchingSuggestion, LibraryFile, Series]:
    root = LibraryRoot(name=f"Main {index}", path=f"/comics/{index}")
    parent = Series(title="Batman", sort_title="batman", comicvine_id=100 + index)
    session.add_all([root, parent])
    await session.flush()

    library_file = LibraryFile(
        file_path=f"/comics/unmatched/{index}/Batman Annual 001.cbz",
        file_name="Batman Annual 001.cbz",
        file_size=1_000,
        file_format=FileFormat.CBZ,
        file_modified_at=datetime(2026, 6, 1, tzinfo=UTC),
        match_confidence=MatchConfidence.UNMATCHED,
        parsed_series="Batman Annual",
        parsed_issue_number=1.0,
        library_root_id=root.id,
    )
    session.add(library_file)
    await session.flush()

    suggestion = MatchingSuggestion(
        library_file_id=library_file.id,
        parent_series_id=parent.id,
        suggested_comicvine_id=200,
        suggested_title="Batman Annual",
        suggested_year=2026,
        suggested_publisher="DC",
        suggested_series_type="annual",
        detection_source="filename",
        confidence_score=0.92,
        reason="Looks like an annual for Batman.",
        status=status,
    )
    session.add(suggestion)
    await session.flush()
    return suggestion, library_file, parent


@pytest.mark.asyncio
class TestSuggestionListingRoutes:
    async def test_list_defaults_to_pending_and_maps_relationship_fields(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            pending, _, _ = await _seed_suggestion_graph(session)
            dismissed, _, _ = await _seed_suggestion_graph(
                session,
                status=SuggestionStatus.DISMISSED,
                index=2,
            )

            default_results = await suggestions_api.list_suggestions(
                object(),  # type: ignore[arg-type]
                session,
            )
            dismissed_results = await suggestions_api.list_suggestions(
                object(),  # type: ignore[arg-type]
                session,
                status=SuggestionStatus.DISMISSED,
            )

        assert [result.id for result in default_results] == [pending.id]
        assert default_results[0].file_name == "Batman Annual 001.cbz"
        assert default_results[0].parent_series_title == "Batman"
        assert [result.id for result in dismissed_results] == [dismissed.id]

    async def test_suggestion_count_returns_pending_total(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            await _seed_suggestion_graph(session)
            await _seed_suggestion_graph(session, index=2)
            await _seed_suggestion_graph(session, status=SuggestionStatus.ACCEPTED, index=3)

            count = await suggestions_api.suggestion_count(
                object(),  # type: ignore[arg-type]
                session,
            )

        assert count == {"pending": 2}


@pytest.mark.asyncio
class TestSuggestionAcceptDismissRoutes:
    async def test_accept_adds_series_marks_suggestion_and_rematches_file(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        added_calls: list[dict[str, object]] = []
        matched_files: list[int] = []

        class FakeSeriesService:
            async def add_from_comicvine(
                self,
                session: AsyncSession,
                *,
                comicvine_id: int,
                library_root_id: int | None,
                search_on_add: bool,
            ) -> SimpleNamespace:
                added_calls.append(
                    {
                        "session": session,
                        "comicvine_id": comicvine_id,
                        "library_root_id": library_root_id,
                        "search_on_add": search_on_add,
                    }
                )
                return SimpleNamespace(id=42, title="Batman Annual")

        class FakeMatchingService:
            async def match_file(self, _session: AsyncSession, library_file: LibraryFile) -> None:
                matched_files.append(library_file.id)

        async def _build_series_service(_session: AsyncSession) -> FakeSeriesService:
            return FakeSeriesService()

        async def _search_on_add(_session: AsyncSession) -> bool:
            return True

        monkeypatch.setattr(
            "pullbox.composition.services.build_domain_series_service",
            _build_series_service,
        )
        monkeypatch.setattr(
            "pullbox.composition.services.build_matching_service",
            lambda: FakeMatchingService(),
        )
        monkeypatch.setattr(suggestions_api, "load_search_on_add_default", _search_on_add)

        async with sec_db() as session:
            suggestion, library_file, _ = await _seed_suggestion_graph(session)

            result = await suggestions_api.accept_suggestion(
                suggestion.id,
                SuggestionAccept(comicvine_id=333, library_root_id=9),
                object(),  # type: ignore[arg-type]
                session,
            )
            await session.refresh(suggestion)

        assert result == {"message": "Added 'Batman Annual' and re-matched file.", "series_id": 42}
        assert suggestion.status == SuggestionStatus.ACCEPTED
        assert suggestion.suggested_comicvine_id == 333
        assert added_calls[0]["comicvine_id"] == 333
        assert added_calls[0]["library_root_id"] == 9
        assert added_calls[0]["search_on_add"] is True
        assert matched_files == [library_file.id]

    async def test_accept_rejects_missing_or_non_pending_suggestion(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            accepted, _, _ = await _seed_suggestion_graph(session, status=SuggestionStatus.ACCEPTED)

            with pytest.raises(NotFoundError):
                await suggestions_api.accept_suggestion(
                    999,
                    SuggestionAccept(comicvine_id=333),
                    object(),  # type: ignore[arg-type]
                    session,
                )

            with pytest.raises(ValidationError):
                await suggestions_api.accept_suggestion(
                    accepted.id,
                    SuggestionAccept(comicvine_id=333),
                    object(),  # type: ignore[arg-type]
                    session,
                )

    async def test_dismiss_marks_suggestion_and_missing_returns_not_found(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            suggestion, _, _ = await _seed_suggestion_graph(session)

            result = await suggestions_api.dismiss_suggestion(
                suggestion.id,
                object(),  # type: ignore[arg-type]
                session,
            )
            await session.flush()
            await session.refresh(suggestion)

            with pytest.raises(NotFoundError):
                await suggestions_api.dismiss_suggestion(
                    999,
                    object(),  # type: ignore[arg-type]
                    session,
                )

        assert result == {"message": "Suggestion dismissed."}
        assert suggestion.status == SuggestionStatus.DISMISSED
