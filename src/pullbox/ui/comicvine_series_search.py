"""Shared ComicVine series search presentation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.core.naming import format_series_folder
from pullbox.models.series import Series
from pullbox.services.comicvine_persistent_cache import PersistentComicVineCacheProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ADD_SERIES_PER_PAGE = 20
COMICVINE_SERIES_SEARCH_LIMIT = 1000
IMPORT_CV_MATCH_DISPLAY_LIMIT = 100

COMICVINE_SERIES_SORT_OPTIONS = [
    ("relevance", "Best Match"),
    ("-year_start", "Newest Year"),
    ("year_start", "Oldest Year"),
    ("-issue_count", "Most Issues"),
    ("title", "Title A-Z"),
]


def request_cache_session_factory(
    request: object,
) -> async_sessionmaker[AsyncSession] | None:
    """Return the app session factory exposed on real UI requests, if available."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    factory = getattr(state, "db_session_factory", None)
    return factory if isinstance(factory, async_sessionmaker) else None


def wrap_comicvine_provider_for_ui_cache(provider: Any, request: object) -> Any:
    """Use persistent ComicVine cache for UI searches when a session factory exists."""
    session_factory = request_cache_session_factory(request)
    if session_factory is None:
        return provider
    return PersistentComicVineCacheProvider(provider, session_factory)


_TRAILING_YEAR_HINT_RE = re.compile(
    r"^(?P<title>.+?)(?:\s+|\s*[\(\[])(?P<year>\d{4})(?:[\)\]])?\s*$"
)


@dataclass(frozen=True, slots=True)
class ComicVineSeriesSearchQuery:
    """Parsed UI search text with an optional ComicVine volume start-year hint."""

    raw_query: str
    title_query: str
    year_hint: int | None = None


def _is_plausible_start_year(year: int) -> bool:
    current_year = date.today().year
    return 1900 <= year <= current_year + 1


def parse_comicvine_series_query(query: str | None) -> ComicVineSeriesSearchQuery:
    """Split a trailing start-year hint from a ComicVine series search query."""
    raw_query = (query or "").strip()
    if not raw_query:
        return ComicVineSeriesSearchQuery(raw_query="", title_query="")

    match = _TRAILING_YEAR_HINT_RE.match(raw_query)
    if match:
        year = int(match.group("year"))
        title_query = match.group("title").strip().rstrip(" -_:,;")
        if title_query and _is_plausible_start_year(year):
            return ComicVineSeriesSearchQuery(
                raw_query=raw_query,
                title_query=title_query,
                year_hint=year,
            )

    return ComicVineSeriesSearchQuery(raw_query=raw_query, title_query=raw_query)


def _object_to_int(value: object) -> int:
    """Best-effort integer coercion for template-facing sort values."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _object_to_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _result_value(item: object, key: str) -> object:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _match_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _without_leading_article(value: str) -> str:
    return re.sub(r"^(the|a|an)\s+", "", value).strip()


def _tokenize_match_key(value: str) -> list[str]:
    return [token for token in value.split() if token]


def _contains_phrase(value: str, phrase: str) -> bool:
    if not value or not phrase:
        return False
    return f" {phrase} " in f" {value} "


def _tokens_appear_in_order(value_tokens: list[str], query_tokens: list[str]) -> bool:
    if not query_tokens:
        return False
    next_query_index = 0
    for token in value_tokens:
        if token == query_tokens[next_query_index]:
            next_query_index += 1
            if next_query_index == len(query_tokens):
                return True
    return False


def _title_relevance_rank(title: object, query: str | None) -> tuple[int, int]:
    normalized_title = _match_key(title)
    normalized_query = _match_key(query)
    if not normalized_query:
        return (6, 0)

    title_without_article = _without_leading_article(normalized_title)
    query_without_article = _without_leading_article(normalized_query)
    title_keys = [normalized_title]
    query_keys = [normalized_query]
    if title_without_article and title_without_article != normalized_title:
        title_keys.append(title_without_article)
    if query_without_article and query_without_article != normalized_query:
        query_keys.append(query_without_article)

    if any(title_key == query_key for title_key in title_keys for query_key in query_keys):
        return (0, 0)
    if any(
        title_key.startswith(query_key)
        for title_key in title_keys
        for query_key in query_keys
        if query_key
    ):
        return (1, 0)
    if any(
        _contains_phrase(title_key, query_key)
        for title_key in title_keys
        for query_key in query_keys
        if query_key
    ):
        return (2, 0)

    title_tokens = _tokenize_match_key(title_without_article or normalized_title)
    query_tokens = _tokenize_match_key(query_without_article or normalized_query)
    title_token_set = set(title_tokens)
    matched_token_count = sum(1 for token in query_tokens if token in title_token_set)

    if matched_token_count == len(query_tokens) and _tokens_appear_in_order(
        title_tokens,
        query_tokens,
    ):
        return (3, 0)
    if matched_token_count == len(query_tokens):
        return (4, 0)
    if matched_token_count > 0:
        return (5, -matched_token_count)
    return (6, 0)


def _title_match_rank(title: object, query: str | None) -> int:
    normalized_title = _match_key(title)
    normalized_query = _match_key(query)
    title_without_article = _without_leading_article(normalized_title)
    query_without_article = _without_leading_article(normalized_query)
    if not normalized_query:
        return 0
    if normalized_title == normalized_query or title_without_article == query_without_article:
        return 0
    if normalized_title.startswith(f"{normalized_query} ") or title_without_article.startswith(
        f"{query_without_article} "
    ):
        return 1
    if normalized_query in normalized_title or query_without_article in title_without_article:
        return 2
    return 3


def _year_match_rank(year_start: object, year_hint: int | None) -> int:
    if year_hint is None:
        return 0
    year = _object_to_optional_int(year_start)
    if year is None:
        return 3
    delta = abs(year - year_hint)
    if delta == 0:
        return 0
    if delta == 1:
        return 1
    return 2


def normalize_comicvine_series_sort(sort: str | None) -> str:
    allowed = {"relevance", "-year_start", "year_start", "-issue_count", "title"}
    return sort if sort in allowed else "relevance"


def sort_comicvine_series_results[T](
    results: list[T],
    sort: str,
    *,
    query: str | None = None,
    year_hint: int | None = None,
) -> list[T]:
    normalized_sort = normalize_comicvine_series_sort(sort)
    if normalized_sort == "title":
        return sorted(
            results,
            key=lambda item: (
                str(_result_value(item, "title") or "").lower(),
                _result_value(item, "year_start") is None,
                _object_to_int(_result_value(item, "year_start")),
            ),
        )
    if normalized_sort == "year_start":
        return sorted(
            results,
            key=lambda item: (
                _result_value(item, "year_start") is None,
                _object_to_int(_result_value(item, "year_start")),
                _title_match_rank(_result_value(item, "title"), query),
                str(_result_value(item, "title") or "").lower(),
            ),
        )
    if normalized_sort == "-year_start":
        return sorted(
            results,
            key=lambda item: (
                _result_value(item, "year_start") is None,
                -(_object_to_int(_result_value(item, "year_start"))),
                _title_match_rank(_result_value(item, "title"), query),
                str(_result_value(item, "title") or "").lower(),
            ),
        )
    if normalized_sort == "-issue_count":
        return sorted(
            results,
            key=lambda item: (
                _result_value(item, "issue_count") is None,
                -(_object_to_int(_result_value(item, "issue_count"))),
                str(_result_value(item, "title") or "").lower(),
            ),
        )
    return [
        item
        for _index, item in sorted(
            enumerate(results),
            key=lambda indexed_item: (
                *_title_relevance_rank(_result_value(indexed_item[1], "title"), query),
                _year_match_rank(_result_value(indexed_item[1], "year_start"), year_hint),
                indexed_item[0],
            ),
        )
    ]


def format_comicvine_series_results(
    results: list[Any],
    *,
    existing_series_by_cv_id: dict[int, int] | None = None,
    folder_template: str = "{Series} ({Year})",
    replace_illegal: bool = True,
    colon_replacement: str = "dash",
) -> list[dict[str, object]]:
    """Convert provider search results into the shared add/search result card shape."""
    existing_series_by_cv_id = existing_series_by_cv_id or {}
    formatted: list[dict[str, object]] = []
    for result in results:
        comicvine_id = int(result.provider_id)
        title = str(getattr(result, "title", "") or "Unknown")
        year_start = _object_to_optional_int(getattr(result, "year_start", None))
        publisher_name = _optional_str(getattr(result, "publisher", None))
        issue_count = _object_to_optional_int(getattr(result, "issue_count", None))
        comicvine_url = _optional_str(getattr(result, "comicvine_url", None))

        formatted.append(
            {
                "comicvine_id": comicvine_id,
                "title": title,
                "year_start": year_start,
                "publisher_name": publisher_name,
                "issue_count": issue_count,
                "description": _optional_str(getattr(result, "description", None)),
                "cover_url": _optional_str(getattr(result, "cover_url", None)),
                "comicvine_url": comicvine_url,
                "folder_preview": format_series_folder(
                    title=title,
                    year=year_start,
                    publisher=publisher_name,
                    template=folder_template,
                    replace_illegal=replace_illegal,
                    colon_replacement=colon_replacement,
                ),
                "already_added": comicvine_id in existing_series_by_cv_id,
                "library_series_id": existing_series_by_cv_id.get(comicvine_id),
                # Legacy aliases keep older import/orphaned result templates compatible.
                "cv_id": comicvine_id,
                "name": title,
                "start_year": year_start,
                "publisher": publisher_name,
                "cv_url": comicvine_url,
            }
        )
    return formatted


async def load_existing_series_by_cv_id(
    session: AsyncSession,
    results: list[Any],
) -> dict[int, int]:
    """Return library series ids keyed by ComicVine volume id for result decoration."""
    comicvine_ids = [int(result.provider_id) for result in results]
    if not comicvine_ids:
        return {}

    existing_result = await session.execute(
        select(Series.id, Series.comicvine_id).where(Series.comicvine_id.in_(comicvine_ids))
    )
    return {
        comicvine_id: series_id
        for series_id, comicvine_id in existing_result.all()
        if comicvine_id is not None
    }
