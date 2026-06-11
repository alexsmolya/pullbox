"""Library browser presenter models and pure helper functions."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from pullbox.core.library_root_resolution import resolve_path_inside_roots

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


@dataclass(frozen=True)
class LibraryGaugeView:
    """Mission-control gauge for the library workspace."""

    key: str
    label: str
    value_label: str
    tone: str
    stroke_offset: float


@dataclass(frozen=True)
class LibraryStatStripItemView:
    """Compact stat cell for the library strip."""

    key: str
    label: str
    value_label: str
    tone: str = "default"
    href: str = ""


@dataclass(frozen=True)
class LibraryFormatPillView:
    """Format distribution pill."""

    key: str
    label: str
    count: int
    tone: str


@dataclass(frozen=True)
class LibraryBrowserTreeNodeView:
    """Left-rail folder node for the library browser shell."""

    key: str
    name: str
    path: str
    kind: str
    root_path: str
    href: str
    is_root: bool = False
    has_children: bool = False
    is_active: bool = False
    is_open: bool = False
    children: tuple[LibraryBrowserTreeNodeView, ...] = ()


@dataclass(frozen=True)
class LibraryBrowserRowView:
    """Row in the read-only library browser shell."""

    key: str
    name: str
    path: str
    kind: str
    root_path: str
    is_folder: bool
    file_format: str | None
    is_convertible: bool
    href: str
    item_count_label: str
    size_label: str
    type_label: str
    type_tone: str
    modified_label: str


@dataclass(frozen=True)
class LibraryBrowserSortableRow:
    """Internal typed sort record for library browser rows."""

    group: int
    name: str
    items: int
    size: int
    type: str
    modified: datetime
    row: LibraryBrowserRowView


@dataclass(frozen=True)
class LibraryBreadcrumbView:
    """Breadcrumb segment for the read-only library browser."""

    key: str
    label: str
    href: str
    is_current: bool = False


@dataclass(frozen=True)
class LibraryWorkspaceView:
    """Aggregated presenter for the redesigned library workspace shell."""

    root_configured: bool
    root_available: bool
    subtitle: str
    root_path: str | None
    current_path: str | None
    root_name: str
    root_summary_label: str
    browser_sort: str
    parent_href: str
    gauges: tuple[LibraryGaugeView, ...]
    stats: tuple[LibraryStatStripItemView, ...]
    format_pills: tuple[LibraryFormatPillView, ...]
    tree_nodes: tuple[LibraryBrowserTreeNodeView, ...]
    breadcrumbs: tuple[LibraryBreadcrumbView, ...]
    browser_rows: tuple[LibraryBrowserRowView, ...]
    browser_empty_title: str
    browser_empty_copy: str
    footer_size_label: str
    footer_free_label: str


LIBRARY_BROWSER_SORT_OPTIONS = {"name", "items", "size", "type", "modified"}


def library_format_pill_tone(format_key: str) -> str:
    """Return the shared pill tone for one library file format."""
    mapping = {
        "cbz": "info",
        "cbr": "neutral",
        "pdf": "warning",
        "cb7": "neutral",
        "cbt": "neutral",
        "epub": "neutral",
    }
    return mapping.get(format_key, "neutral")


def library_stat_tone(key: str) -> str:
    """Return the stat-strip tone for a metric."""
    mapping = {
        "storage-used": "info",
        "cbz-coverage": "success",
        "match-rate": "success",
        "avg-issue": "default",
        "disk-free": "default",
    }
    return mapping.get(key, "default")


def library_file_type_tone(type_label: str) -> str:
    """Return the pill tone for a browser-row type badge."""
    mapping = {
        "Folder": "neutral",
        "CBZ": "info",
        "PDF": "warning",
    }
    return mapping.get(type_label, "neutral")


def library_file_format_label(name: str) -> str | None:
    """Infer a display file-format token from a filesystem name."""
    suffix = Path(name).suffix.lstrip(".").lower()
    return suffix.upper() if suffix else None


def library_is_convertible_file_format(file_format: str | None) -> bool:
    """Return True when the file format supports single-file CBZ conversion."""
    return (file_format or "").strip().lower() in {"cbr", "cb7", "pdf"}


def library_mix_label(directory_count: int, file_count: int) -> str:
    """Return a compact root mix label."""
    parts: list[str] = []
    if directory_count > 0:
        parts.append(f"{directory_count} folder{'s' if directory_count != 1 else ''}")
    if file_count > 0:
        parts.append(f"{file_count} file{'s' if file_count != 1 else ''}")
    return " · ".join(parts) if parts else "No entries yet"


def normalize_library_browser_sort(sort: str | None) -> str:
    """Return a safe library browser sort key."""
    if not sort:
        return "name"
    field = sort.lstrip("-")
    if field not in LIBRARY_BROWSER_SORT_OPTIONS:
        return "name"
    return f"-{field}" if sort.startswith("-") else field


def library_browser_sort_value(
    row: LibraryBrowserSortableRow,
    sort_field: str,
) -> str | int | datetime:
    """Return the active typed sort value for a library browser row."""
    if sort_field == "items":
        return row.items
    if sort_field == "size":
        return row.size
    if sort_field == "type":
        return row.type
    if sort_field == "modified":
        return row.modified
    return row.name


def library_href(path: Path | str | None = None, sort: str | None = None) -> str:
    """Return a safe library browse URL."""
    params: dict[str, str] = {}
    if path is not None:
        params["path"] = str(path)
    if sort:
        params["sort"] = sort
    if not params:
        return "/library"
    return f"/library?{urlencode(params)}"


def library_clamp_browse_path(
    requested_path: str | None,
    *,
    allowed_roots: Sequence[Path],
    default_root: Path | None,
) -> tuple[Path | None, Path | None]:
    """Resolve a requested browse path within the enabled library roots."""
    if not allowed_roots:
        if default_root is None:
            return None, None
        resolved_default = default_root.expanduser().resolve()
        if not resolved_default.exists() or not resolved_default.is_dir():
            return None, None
        return resolved_default, resolved_default

    roots = [root.expanduser().resolve() for root in allowed_roots]
    fallback_root = (default_root or roots[0]).expanduser().resolve()
    if fallback_root not in roots:
        fallback_root = roots[0]

    candidate = fallback_root
    if requested_path:
        with contextlib.suppress(OSError, RuntimeError, ValueError):
            requested = resolve_path_inside_roots(requested_path, roots, require_dir=True)
            matching_root = next(
                (root for root in roots if requested == root or requested.is_relative_to(root)),
                None,
            )
            if matching_root is not None:
                return requested, matching_root

    return candidate, fallback_root


def library_browser_empty_state(
    *,
    root_path: Path | None,
    current_path: Path | None,
    root_available: bool,
) -> tuple[str, str]:
    """Return the empty-state copy for the active library browser location."""
    if root_path is not None and not root_available:
        return (
            "Configured root is unavailable",
            "Pullbox can see the configured library path, but it is not currently "
            "reachable on disk.",
        )

    if (
        root_path is not None
        and current_path is not None
        and root_available
        and current_path != root_path
    ):
        return (
            "Folder is empty",
            "This folder does not contain any visible files or subfolders yet.",
        )

    return (
        "Library root is empty",
        "Import a collection or let completed downloads land here, and this "
        "browser will turn into the working view of your library.",
    )
