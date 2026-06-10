"""Shared library ingest and naming policy helpers.

This module centralizes the runtime naming and ingest settings that should be
shared across imports, downloader post-processing, and library utilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pullbox.core.config_resolver import load_system_config_values, parse_bool

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class LibraryNamingPolicy:
    """Effective naming policy resolved from ``SystemConfig``."""

    rename_on_import: bool
    series_folder_template: str
    comic_file_template: str
    annual_file_template: str
    non_standard_file_template: str
    single_non_standard_file_template: str
    replace_illegal_characters: bool
    colon_replacement: str


@dataclass(frozen=True, slots=True)
class LibraryIngestPolicy(LibraryNamingPolicy):
    """Effective ingest policy resolved from ``SystemConfig``."""

    post_processing_method: str
    torrent_import_strategy: str
    normalize_imported_archives_to_cbz: bool
    skip_existing_files: bool
    update_embedded_comicinfo_from_match: bool


_NAMING_KEYS = (
    "rename_on_import",
    "series_folder_template",
    "comic_file_template",
    "annual_file_template",
    "non_standard_file_template",
    "single_non_standard_file_template",
    "replace_illegal_characters",
    "colon_replacement",
)

_INGEST_KEYS = (
    *_NAMING_KEYS,
    "post_processing_method",
    "torrent_import_strategy",
    "convert_to_preferred_format_on_import",
    "skip_existing_files",
    "update_embedded_comicinfo_from_match_on_import",
)


def serialize_library_ingest_policy(policy: LibraryIngestPolicy) -> dict[str, object]:
    """Return a durable JSON snapshot of the effective ingest policy."""
    return asdict(policy)


def library_ingest_policy_from_snapshot(
    snapshot: Mapping[str, Any] | None,
) -> LibraryIngestPolicy | None:
    """Rehydrate a stored ingest policy snapshot, if it is complete."""
    if not snapshot:
        return None

    try:
        return LibraryIngestPolicy(
            rename_on_import=parse_bool(snapshot["rename_on_import"]),
            series_folder_template=_snapshot_text(snapshot, "series_folder_template"),
            comic_file_template=_snapshot_text(snapshot, "comic_file_template"),
            annual_file_template=_snapshot_text(snapshot, "annual_file_template"),
            non_standard_file_template=_snapshot_text(
                snapshot,
                "non_standard_file_template",
            ),
            single_non_standard_file_template=_snapshot_text(
                snapshot,
                "single_non_standard_file_template",
            ),
            replace_illegal_characters=parse_bool(snapshot["replace_illegal_characters"]),
            colon_replacement=_snapshot_text(snapshot, "colon_replacement"),
            post_processing_method=_snapshot_text(snapshot, "post_processing_method"),
            torrent_import_strategy=_snapshot_text(snapshot, "torrent_import_strategy"),
            normalize_imported_archives_to_cbz=parse_bool(
                snapshot["normalize_imported_archives_to_cbz"]
            ),
            skip_existing_files=parse_bool(snapshot["skip_existing_files"]),
            update_embedded_comicinfo_from_match=parse_bool(
                snapshot["update_embedded_comicinfo_from_match"]
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _snapshot_text(snapshot: Mapping[str, Any], key: str) -> str:
    value = snapshot[key]
    if value is None:
        raise ValueError(f"missing snapshot value: {key}")
    return str(value)


def _library_naming_policy_from_configs(configs: Mapping[str, str]) -> LibraryNamingPolicy:
    """Build the naming-policy portion from already-loaded config values."""
    return LibraryNamingPolicy(
        rename_on_import=parse_bool(configs["rename_on_import"]),
        series_folder_template=configs["series_folder_template"],
        comic_file_template=configs["comic_file_template"],
        annual_file_template=configs["annual_file_template"],
        non_standard_file_template=configs["non_standard_file_template"],
        single_non_standard_file_template=configs["single_non_standard_file_template"],
        replace_illegal_characters=parse_bool(configs["replace_illegal_characters"]),
        colon_replacement=configs["colon_replacement"],
    )


async def load_library_naming_policy(session: AsyncSession) -> LibraryNamingPolicy:
    """Load the effective library naming policy from ``SystemConfig``."""
    configs = await load_system_config_values(session, _NAMING_KEYS)
    return _library_naming_policy_from_configs(configs)


async def load_library_ingest_policy(session: AsyncSession) -> LibraryIngestPolicy:
    """Load the effective library ingest policy from ``SystemConfig``."""
    configs = await load_system_config_values(session, _INGEST_KEYS)
    naming = _library_naming_policy_from_configs(configs)
    return LibraryIngestPolicy(
        rename_on_import=naming.rename_on_import,
        series_folder_template=naming.series_folder_template,
        comic_file_template=naming.comic_file_template,
        annual_file_template=naming.annual_file_template,
        non_standard_file_template=naming.non_standard_file_template,
        single_non_standard_file_template=naming.single_non_standard_file_template,
        replace_illegal_characters=naming.replace_illegal_characters,
        colon_replacement=naming.colon_replacement,
        post_processing_method=configs["post_processing_method"],
        torrent_import_strategy=configs["torrent_import_strategy"],
        normalize_imported_archives_to_cbz=parse_bool(
            configs["convert_to_preferred_format_on_import"]
        ),
        skip_existing_files=parse_bool(configs["skip_existing_files"]),
        update_embedded_comicinfo_from_match=parse_bool(
            configs["update_embedded_comicinfo_from_match_on_import"]
        ),
    )


async def load_search_on_add_default(session: AsyncSession) -> bool:
    """Load the effective global search-on-add default from ``SystemConfig``."""
    configs = await load_system_config_values(session, ("search_on_add_default",))
    return parse_bool(configs["search_on_add_default"])
