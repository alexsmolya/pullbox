"""Target issue lookup helpers for import file matching."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select as sa_select

from pullbox.core.exceptions import ImportProviderDegradedError
from pullbox.core.naming import detect_issue_type
from pullbox.core.release_parser import parse_release_title
from pullbox.core.source_metadata import volume_subtitle_hint_from_filename
from pullbox.models.issue import Issue, IssueType
from pullbox.models.library import LibraryFile
from pullbox.models.series import Series
from pullbox.providers.base import IssueSummary
from pullbox.services.import_embedded_title_match import embedded_issue_number_title_match
from pullbox.services.import_file_issue_signals import candidate_issue_number

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.import_job import ImportedFile, ImportedSeries
    from pullbox.providers.base import MetadataProvider


FileMatchTargetEntry = tuple[int | None, int | None, bool, Issue | None, str | None]
_FULL_SERIES_FETCH_ISSUE_COUNT_LIMIT = 250
PROVIDER_ZERO_ISSUE_PLACEHOLDER_KIND = "provider_zero_issue_placeholder"
PROVIDER_ZERO_ISSUE_PLACEHOLDER_METHOD = "provider_zero_issue_single_issue"
PROVIDER_MISSING_ISSUE_PLACEHOLDER_KIND = "provider_missing_issue_placeholder"
PROVIDER_MISSING_ISSUE_PLACEHOLDER_METHOD = "import_reconcile_provisional_issue"
_PLACEHOLDER_ISSUE_TYPES = frozenset({IssueType.ONE_SHOT, IssueType.SPECIAL})


@dataclass(slots=True)
class FileMatchTargetIndex:
    """Issue lookup maps used while matching imported files."""

    cv_id_map: dict[int, FileMatchTargetEntry] = field(default_factory=dict)
    number_map: dict[float, FileMatchTargetEntry] = field(default_factory=dict)
    synthetic_issue_types: dict[float, IssueType] = field(default_factory=dict)
    synthetic_issue_titles: dict[float, str | None] = field(default_factory=dict)
    existing_series: Series | None = None
    issue_entries: list[tuple[Issue, bool]] = field(default_factory=list)

    @property
    def has_targets(self) -> bool:
        """Return True when at least one target issue identity is available."""
        return bool(self.cv_id_map or self.number_map)


@dataclass(frozen=True, slots=True)
class _IssueSummaryLoadResult:
    summaries: list[IssueSummary]
    exhaustive: bool


async def load_file_match_target_index(
    session: AsyncSession,
    imp_series: ImportedSeries,
    *,
    duplicate_series: bool,
    metadata_provider: MetadataProvider | None,
    files: list[ImportedFile] | None = None,
) -> FileMatchTargetIndex:
    """Load issue identity maps for a matched or duplicate imported series."""
    target_index = FileMatchTargetIndex()

    if imp_series.series_id is not None:
        target_index.existing_series = await session.get(Series, imp_series.series_id)
        issues_result = await session.execute(
            sa_select(Issue, LibraryFile.id)
            .outerjoin(LibraryFile, LibraryFile.issue_id == Issue.id)
            .where(Issue.series_id == imp_series.series_id)
        )
        for issue, library_file_id in issues_result.all():
            has_library_file = library_file_id is not None
            target_index.issue_entries.append((issue, has_library_file))
            entry = (issue.id, issue.comicvine_id, has_library_file, issue, issue.title)
            if issue.comicvine_id is not None:
                target_index.cv_id_map[issue.comicvine_id] = entry
            target_index.number_map[issue.issue_number] = entry
        return target_index

    if imp_series.cv_id is not None and metadata_provider is not None:
        try:
            load_result = await _load_provider_issue_summaries(
                metadata_provider,
                str(imp_series.cv_id),
                files=files,
                issue_count=imp_series.cv_issue_count,
                target_series_title=imp_series.cv_title or imp_series.raw_series_name,
            )
        except Exception as exc:
            raise ImportProviderDegradedError(
                provider="ComicVine",
                query=imp_series.raw_series_name,
                year=imp_series.raw_year,
                attempts=1,
                last_error=str(exc),
            ) from exc
        if not load_result.summaries and load_result.exhaustive and imp_series.cv_issue_count != 0:
            raise ImportProviderDegradedError(
                provider="ComicVine",
                query=imp_series.raw_series_name,
                year=imp_series.raw_year,
                attempts=1,
                last_error=(
                    "Matched series returned no issue targets from ComicVine "
                    f"(cv_id={imp_series.cv_id})."
                ),
            )
        placeholder = _provider_zero_issue_placeholder_target(imp_series, files or [])
        if not load_result.summaries and load_result.exhaustive and placeholder is not None:
            issue_number, issue_type, issue_title = placeholder
            target_index.number_map[issue_number] = (None, None, False, None, issue_title)
            target_index.synthetic_issue_types[issue_number] = issue_type
            target_index.synthetic_issue_titles[issue_number] = issue_title
        for summary in load_result.summaries:
            provider_id = int(summary.provider_id) if summary.provider_id else None
            entry = (None, provider_id, False, None, summary.title)
            if provider_id is not None:
                target_index.cv_id_map[provider_id] = entry
            target_index.number_map[summary.issue_number] = entry

    return target_index


async def _load_provider_issue_summaries(
    metadata_provider: MetadataProvider,
    series_provider_id: str,
    *,
    files: list[ImportedFile] | None,
    issue_count: int | None,
    target_series_title: str | None,
) -> _IssueSummaryLoadResult:
    """Load just enough issue targets to match the incoming files when possible."""
    if not files:
        return _IssueSummaryLoadResult(
            summaries=await metadata_provider.get_issues_for_series(series_provider_id),
            exhaustive=True,
        )

    requested_issue_ids = _requested_issue_ids(files)
    requested_issue_numbers = _requested_issue_numbers(files)
    unresolved_file_count = sum(
        1
        for imp_file in files
        if imp_file.comicvine_issue_id is None and candidate_issue_number(imp_file) is None
    )
    summaries: list[IssueSummary] = []

    if requested_issue_ids:
        summaries.extend(
            await _load_issue_summaries_by_issue_ids(
                metadata_provider,
                series_provider_id,
                requested_issue_ids,
            )
        )

    targeted_issue_fetcher = getattr(metadata_provider, "get_issues_for_series_by_numbers", None)
    supports_targeted_issue_fetch = callable(
        getattr(type(metadata_provider), "get_issues_for_series_by_numbers", None)
    )
    if (
        requested_issue_numbers
        and supports_targeted_issue_fetch
        and callable(targeted_issue_fetcher)
    ):
        if _should_full_fetch_single_issue_volume_subtitle(issue_count, files):
            full_summaries = await metadata_provider.get_issues_for_series(series_provider_id)
            return _IssueSummaryLoadResult(
                summaries=_dedupe_issue_summaries([*summaries, *full_summaries]),
                exhaustive=True,
            )
        if _should_full_fetch_single_issue_embedded_number_title(
            issue_count,
            files,
            target_series_title=target_series_title,
        ):
            full_summaries = await metadata_provider.get_issues_for_series(series_provider_id)
            return _IssueSummaryLoadResult(
                summaries=_dedupe_issue_summaries([*summaries, *full_summaries]),
                exhaustive=True,
            )
        if _should_full_fetch_requested_issue_numbers(
            issue_count,
            requested_count=len(requested_issue_numbers),
        ):
            full_summaries = await metadata_provider.get_issues_for_series(series_provider_id)
            return _IssueSummaryLoadResult(
                summaries=_dedupe_issue_summaries([*summaries, *full_summaries]),
                exhaustive=True,
            )
        summaries.extend(await targeted_issue_fetcher(series_provider_id, requested_issue_numbers))
    elif requested_issue_numbers:
        return _IssueSummaryLoadResult(
            summaries=await metadata_provider.get_issues_for_series(series_provider_id),
            exhaustive=True,
        )

    if not requested_issue_ids and not requested_issue_numbers:
        if _should_skip_full_issue_fetch(issue_count):
            return _IssueSummaryLoadResult(summaries=[], exhaustive=False)
        return _IssueSummaryLoadResult(
            summaries=await metadata_provider.get_issues_for_series(series_provider_id),
            exhaustive=True,
        )

    if unresolved_file_count and not _should_skip_full_issue_fetch(issue_count):
        full_summaries = await metadata_provider.get_issues_for_series(series_provider_id)
        return _IssueSummaryLoadResult(
            summaries=_dedupe_issue_summaries([*summaries, *full_summaries]),
            exhaustive=True,
        )

    return _IssueSummaryLoadResult(summaries=_dedupe_issue_summaries(summaries), exhaustive=False)


def _requested_issue_ids(files: list[ImportedFile]) -> list[int]:
    issue_ids = {
        int(imp_file.comicvine_issue_id)
        for imp_file in files
        if imp_file.comicvine_issue_id is not None
    }
    return sorted(issue_ids)


def _requested_issue_numbers(files: list[ImportedFile]) -> list[float]:
    issue_numbers = {
        float(issue_number)
        for imp_file in files
        if (issue_number := candidate_issue_number(imp_file)) is not None
    }
    return sorted(issue_numbers)


async def _load_issue_summaries_by_issue_ids(
    metadata_provider: MetadataProvider,
    series_provider_id: str,
    issue_ids: list[int],
) -> list[IssueSummary]:
    summaries: list[IssueSummary] = []
    for issue_id in issue_ids:
        issue = await metadata_provider.get_issue(str(issue_id))
        if str(issue.series_provider_id) != str(series_provider_id):
            continue
        summaries.append(
            IssueSummary(
                provider_id=str(issue.provider_id),
                issue_number=issue.issue_number,
                title=issue.title,
                release_date=issue.release_date,
                cover_url=issue.cover_url,
                issue_type=detect_issue_type(issue.title or ""),
            )
        )
    return summaries


def _should_skip_full_issue_fetch(issue_count: int | None) -> bool:
    return issue_count is not None and issue_count > _FULL_SERIES_FETCH_ISSUE_COUNT_LIMIT


def _should_full_fetch_single_issue_volume_subtitle(
    issue_count: int | None,
    files: list[ImportedFile],
) -> bool:
    """Load issue #1 for one-issue collection volumes split from source volume ordinals."""
    if issue_count != 1:
        return False
    for imp_file in files:
        requested_issue_number = candidate_issue_number(imp_file)
        if requested_issue_number is None or requested_issue_number == 1.0:
            continue
        if volume_subtitle_hint_from_filename(imp_file.file_name or "") is not None:
            return True
    return False


def _should_full_fetch_single_issue_embedded_number_title(
    issue_count: int | None,
    files: list[ImportedFile],
    *,
    target_series_title: str | None,
) -> bool:
    """Load issue #1 when a one-issue provider title embeds the parsed issue number."""
    if issue_count != 1:
        return False
    for imp_file in files:
        issue_number = candidate_issue_number(imp_file)
        if embedded_issue_number_title_match(
            source_series_name=imp_file.parsed_series,
            original_title=imp_file.file_name,
            target_series_title=target_series_title,
            issue_number=issue_number,
        ):
            return True
    return False


def _should_full_fetch_requested_issue_numbers(
    issue_count: int | None,
    *,
    requested_count: int,
) -> bool:
    """Prefer full issue lists when they are no more expensive than targeted calls."""
    if requested_count <= 1 or issue_count is None or _should_skip_full_issue_fetch(issue_count):
        return False
    estimated_full_pages = max(1, math.ceil(max(issue_count, 1) / 100))
    return estimated_full_pages <= requested_count


def _provider_zero_issue_placeholder_target(
    imp_series: ImportedSeries,
    files: list[ImportedFile],
) -> tuple[float, IssueType, str | None] | None:
    """Return a synthetic issue target for exact one-shot/special volumes with no issues."""
    if imp_series.cv_issue_count != 0 or len(files) != 1:
        return None
    if not (
        imp_series.cv_match_method == "exact_title_year"
        or (imp_series.cv_match_score is not None and imp_series.cv_match_score >= 0.9)
    ):
        return None

    imp_file = files[0]
    if imp_file.comicvine_issue_id is not None:
        return None

    requested_issue_number = candidate_issue_number(imp_file)
    if requested_issue_number is not None and abs(float(requested_issue_number) - 1.0) >= 0.0001:
        return None

    issue_type = _file_placeholder_issue_type(imp_file) or _series_placeholder_issue_type(
        imp_series
    )
    if issue_type not in _PLACEHOLDER_ISSUE_TYPES:
        return None

    return (
        float(requested_issue_number) if requested_issue_number is not None else 1.0,
        issue_type,
        imp_series.cv_title or imp_series.raw_series_name,
    )


def _file_placeholder_issue_type(imp_file: ImportedFile) -> IssueType | None:
    diagnostics = imp_file.diagnostics if isinstance(imp_file.diagnostics, dict) else {}
    raw_issue_type = diagnostics.get("source_issue_type")
    issue_type = _coerce_issue_type(raw_issue_type)
    if issue_type is not None:
        return issue_type

    source_metadata = diagnostics.get("source_metadata")
    filename_parse = (
        source_metadata.get("filename_parse") if isinstance(source_metadata, dict) else None
    )
    raw_issue_type = filename_parse.get("issue_type") if isinstance(filename_parse, dict) else None
    issue_type = _coerce_issue_type(raw_issue_type)
    if issue_type is not None:
        return issue_type

    parsed = parse_release_title(imp_file.file_name or "")
    return parsed.issue_type if parsed is not None else None


def _series_placeholder_issue_type(imp_series: ImportedSeries) -> IssueType | None:
    diagnostics = imp_series.diagnostics if isinstance(imp_series.diagnostics, dict) else {}
    return _coerce_issue_type(diagnostics.get("source_issue_type"))


def _coerce_issue_type(raw_issue_type: object) -> IssueType | None:
    if not raw_issue_type:
        return None
    try:
        return IssueType(str(raw_issue_type))
    except ValueError:
        return None


def _dedupe_issue_summaries(summaries: list[IssueSummary]) -> list[IssueSummary]:
    deduped: dict[tuple[str, float], IssueSummary] = {}
    for summary in summaries:
        key = (str(summary.provider_id), float(summary.issue_number))
        deduped[key] = summary
    return list(deduped.values())
