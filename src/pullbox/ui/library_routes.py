"""Library browser UI route and view helpers."""

import asyncio
import contextlib
import os
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.models.issue import Issue
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.ui.library_presenters import (
    LibraryBreadcrumbView,
    LibraryBrowserRowView,
    LibraryBrowserSortableRow,
    LibraryBrowserTreeNodeView,
    LibraryFormatPillView,
    LibraryGaugeView,
    LibraryStatStripItemView,
    LibraryWorkspaceView,
    library_browser_empty_state,
    library_browser_sort_value,
    library_clamp_browse_path,
    library_file_format_label,
    library_file_type_tone,
    library_format_pill_tone,
    library_href,
    library_is_convertible_file_format,
    library_mix_label,
    library_stat_tone,
    normalize_library_browser_sort,
)

router = APIRouter()

__all__ = [
    "LibraryBreadcrumbView",
    "LibraryBrowserRowView",
    "LibraryBrowserSortableRow",
    "LibraryBrowserTreeNodeView",
    "LibraryFormatPillView",
    "LibraryGaugeView",
    "LibraryStatStripItemView",
    "LibraryWorkspaceView",
    "build_library_browser_snapshot",
    "build_library_workspace_view",
    "library",
    "library_browser_empty_state",
    "library_browser_sort_value",
    "library_clamp_browse_path",
    "library_file_format_label",
    "library_file_type_tone",
    "library_format_pill_tone",
    "library_href",
    "library_is_convertible_file_format",
    "library_mix_label",
    "library_stat_tone",
    "load_library_series_preview_metrics",
    "normalize_library_browser_sort",
]

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]
_LoadSystemConfigValues = Callable[[AsyncSession, Sequence[str]], Awaitable[Mapping[str, str]]]
_BuildRenameTemplates = Callable[[Mapping[str, str]], dict[str, str]]
_ResolveUtilityBrowsePaths = Callable[[dict[str, str]], dict[str, str]]
_FormatFilesize = Callable[[int], str]
_FormatLocaltime = Callable[..., str]
_DashboardGaugeOffset = Callable[[float], float]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None
_load_system_config_values: _LoadSystemConfigValues | None = None
_build_rename_templates: _BuildRenameTemplates | None = None
_resolve_utility_browse_paths: _ResolveUtilityBrowsePaths | None = None
_format_filesize: _FormatFilesize | None = None
_format_localtime: _FormatLocaltime | None = None
_dashboard_gauge_offset: _DashboardGaugeOffset | None = None


def configure_library_routes(
    *,
    get_templates: _GetTemplates,
    build_context: _BuildContext,
    load_system_config_values: _LoadSystemConfigValues,
    build_rename_templates: _BuildRenameTemplates,
    resolve_utility_browse_paths: _ResolveUtilityBrowsePaths,
    format_filesize: _FormatFilesize,
    format_localtime: _FormatLocaltime,
    dashboard_gauge_offset: _DashboardGaugeOffset,
) -> None:
    """Provide shared UI runtime dependencies from the facade module."""
    global _get_templates
    global _build_context
    global _load_system_config_values
    global _build_rename_templates
    global _resolve_utility_browse_paths
    global _format_filesize
    global _format_localtime
    global _dashboard_gauge_offset
    _get_templates = get_templates
    _build_context = build_context
    _load_system_config_values = load_system_config_values
    _build_rename_templates = build_rename_templates
    _resolve_utility_browse_paths = resolve_utility_browse_paths
    _format_filesize = format_filesize
    _format_localtime = format_localtime
    _dashboard_gauge_offset = dashboard_gauge_offset
    get_templates().env.globals["library_href"] = library_href


def _templates() -> Jinja2Templates:
    if _get_templates is None:
        msg = "library routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "library routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


async def _system_config_values(
    session: AsyncSession,
    keys: Sequence[str],
) -> dict[str, str]:
    if _load_system_config_values is None:
        msg = "library routes have not been configured with system config loader"
        raise RuntimeError(msg)
    values = await _load_system_config_values(session, keys)
    return dict(values)


def _rename_templates(configs: Mapping[str, str]) -> dict[str, str]:
    if _build_rename_templates is None:
        msg = "library routes have not been configured with rename template builder"
        raise RuntimeError(msg)
    return _build_rename_templates(configs)


def _utility_browse_paths(configs: dict[str, str]) -> dict[str, str]:
    if _resolve_utility_browse_paths is None:
        msg = "library routes have not been configured with utility path resolver"
        raise RuntimeError(msg)
    return _resolve_utility_browse_paths(configs)


def _filesize(value: int) -> str:
    if _format_filesize is None:
        msg = "library routes have not been configured with filesize formatter"
        raise RuntimeError(msg)
    return _format_filesize(value)


def _localtime(value: date | datetime | None, fmt: str | None = None) -> str:
    if _format_localtime is None:
        msg = "library routes have not been configured with localtime formatter"
        raise RuntimeError(msg)
    return _format_localtime(value, fmt)


def _gauge_offset(value: float) -> float:
    if _dashboard_gauge_offset is None:
        msg = "library routes have not been configured with gauge helper"
        raise RuntimeError(msg)
    return _dashboard_gauge_offset(value)


async def load_library_series_preview_metrics(
    session: AsyncSession,
    comics_dir: Path | None,
) -> dict[str, tuple[int, int, datetime | None]]:
    """Load DB-backed size/count hints for series folders under the library root."""
    stmt = (
        select(
            Series.path,
            func.count(LibraryFile.id),
            func.coalesce(func.sum(LibraryFile.file_size), 0),
            func.max(LibraryFile.file_modified_at),
        )
        .outerjoin(Issue, Issue.series_id == Series.id)
        .outerjoin(LibraryFile, LibraryFile.issue_id == Issue.id)
        .where(Series.path.is_not(None))
        .group_by(Series.path)
    )
    if comics_dir is not None:
        root_prefix = comics_dir.as_posix().rstrip("/")
        stmt = stmt.where(
            or_(
                Series.path == root_prefix,
                Series.path.like(f"{root_prefix}/%"),
            )
        )

    result = await session.execute(stmt)
    metrics: dict[str, tuple[int, int, datetime | None]] = {}
    for path, file_count, size_total, modified_at in result.all():
        if not path:
            continue
        metrics[str(path)] = (
            int(file_count or 0),
            int(size_total or 0),
            modified_at if isinstance(modified_at, datetime) else None,
        )
    return metrics


def build_library_browser_snapshot(
    current_path: Path | None,
    *,
    active_root: Path | None,
    library_roots: Sequence[LibraryRoot],
    series_metrics: Mapping[str, tuple[int, int, datetime | None]],
    total_size_bytes: int,
    browser_sort: str,
) -> tuple[
    bool,
    str,
    str,
    tuple[LibraryBrowserTreeNodeView, ...],
    tuple[LibraryBreadcrumbView, ...],
    tuple[LibraryBrowserRowView, ...],
]:
    """Return a read-only browser snapshot for the current library path."""
    if current_path is None or active_root is None:
        return False, "", "No root configured", (), (), ()

    resolved_root = active_root.expanduser().resolve()
    resolved_current = current_path.expanduser().resolve()
    if not resolved_current.exists() or not resolved_current.is_dir():
        return False, str(resolved_current), "Configured root is unavailable", (), (), ()

    normalized_sort = normalize_library_browser_sort(browser_sort)
    sort_field = normalized_sort.lstrip("-")
    sort_desc = normalized_sort.startswith("-")

    def _scan() -> tuple[
        list[tuple[str, str, bool, int | None, datetime | None]],
        list[tuple[str, str, bool, int | None, datetime | None]],
    ]:
        directories: list[tuple[str, str, bool, int | None, datetime | None]] = []
        files: list[tuple[str, str, bool, int | None, datetime | None]] = []
        with os.scandir(resolved_current) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                record = (
                    entry.name,
                    entry.path,
                    is_dir,
                    stat.st_size if not is_dir else None,
                    modified_at,
                )
                if is_dir:
                    directories.append(record)
                else:
                    files.append(record)
        directories.sort(key=lambda row: row[0].lower())
        files.sort(key=lambda row: row[0].lower())
        return directories, files

    def _count_children(path_str: str) -> int:
        try:
            with os.scandir(path_str) as children:
                return sum(1 for child in children if not child.name.startswith("."))
        except OSError:
            return 0

    directories, files = _scan()

    def _scan_visible_directories(path_obj: Path) -> list[Path]:
        directories: list[Path] = []
        try:
            with os.scandir(path_obj) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            directories.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            return []
        directories.sort(key=lambda item: item.name.lower())
        return directories

    def _build_tree_node(
        node_path: Path,
        *,
        node_key: str,
        node_name: str,
        root_path: Path,
    ) -> LibraryBrowserTreeNodeView:
        child_paths = _scan_visible_directories(node_path)
        children = tuple(
            _build_tree_node(
                child_path,
                node_key=f"{node_key}-{index}",
                node_name=child_path.name,
                root_path=root_path,
            )
            for index, child_path in enumerate(child_paths, start=1)
        )
        is_open = node_path == resolved_current or node_path in resolved_current.parents
        return LibraryBrowserTreeNodeView(
            key=node_key,
            name=node_name,
            path=str(node_path),
            kind="root" if node_path == root_path else "folder",
            root_path=str(root_path),
            href=library_href(node_path, normalized_sort),
            is_root=node_path == root_path,
            has_children=bool(children),
            is_active=node_path == resolved_current,
            is_open=is_open,
            children=children,
        )

    directory_count = len(directories)
    file_count = len(files)
    total_mix_label = library_mix_label(directory_count, file_count)
    tree_nodes = tuple(
        _build_tree_node(
            root_path := Path(root.path).expanduser().resolve(),
            node_key=f"root-{root.id}",
            node_name=root.name,
            root_path=root_path,
        )
        for root in library_roots
        if root.enabled
    )

    relative_parts = []
    if resolved_current != resolved_root:
        with contextlib.suppress(ValueError):
            relative_parts = list(resolved_current.relative_to(resolved_root).parts)

    breadcrumb_paths = [resolved_root]
    cursor = resolved_root
    for part in relative_parts:
        cursor = cursor / part
        breadcrumb_paths.append(cursor)

    breadcrumbs = tuple(
        LibraryBreadcrumbView(
            key=f"crumb-{index}",
            label=(path.name or str(path)),
            href=library_href(path, normalized_sort),
            is_current=index == len(breadcrumb_paths) - 1,
        )
        for index, path in enumerate(breadcrumb_paths)
    )

    sortable_rows: list[LibraryBrowserSortableRow] = []

    for index, (name, entry_path, _is_dir, _file_size, modified_at) in enumerate(
        directories, start=1
    ):
        metric = series_metrics.get(entry_path)
        item_count = metric[0] if metric is not None else _count_children(entry_path)
        size_bytes = metric[1] if metric is not None else 0
        modified_value = metric[2] if metric and metric[2] is not None else modified_at
        sortable_rows.append(
            LibraryBrowserSortableRow(
                group=0,
                name=name.lower(),
                items=item_count,
                size=size_bytes,
                type="folder",
                modified=modified_value or datetime.min.replace(tzinfo=UTC),
                row=LibraryBrowserRowView(
                    key=f"row-dir-{index}",
                    name=name,
                    path=entry_path,
                    kind="folder",
                    root_path=str(resolved_root),
                    href=library_href(entry_path, normalized_sort),
                    is_folder=True,
                    file_format=None,
                    is_convertible=False,
                    item_count_label=str(item_count),
                    size_label=_filesize(size_bytes) if size_bytes > 0 else "—",
                    type_label="Folder",
                    type_tone="neutral",
                    modified_label=(
                        _localtime(modified_value) if isinstance(modified_value, datetime) else "—"
                    ),
                ),
            )
        )

    for index, (name, entry_path, _is_dir, file_size, modified_at) in enumerate(files, start=1):
        file_format = library_file_format_label(name)
        type_label = file_format or "FILE"
        sortable_rows.append(
            LibraryBrowserSortableRow(
                group=1,
                name=name.lower(),
                items=0,
                size=int(file_size or 0),
                type=type_label.lower(),
                modified=modified_at or datetime.min.replace(tzinfo=UTC),
                row=LibraryBrowserRowView(
                    key=f"row-file-{index}",
                    name=name,
                    path=entry_path,
                    kind="file",
                    root_path=str(resolved_root),
                    href="",
                    is_folder=False,
                    file_format=file_format,
                    is_convertible=library_is_convertible_file_format(file_format),
                    item_count_label="—",
                    size_label=_filesize(int(file_size or 0)),
                    type_label=type_label,
                    type_tone=library_file_type_tone(type_label),
                    modified_label=(
                        _localtime(modified_at) if isinstance(modified_at, datetime) else "—"
                    ),
                ),
            )
        )

    rows = [
        row_data.row
        for row_data in sorted(
            sortable_rows,
            key=lambda row_data: (
                row_data.group,
                library_browser_sort_value(row_data, sort_field),
                row_data.name,
            ),
            reverse=sort_desc,
        )
    ]
    if sort_desc:
        rows.sort(key=lambda row: 0 if row.is_folder else 1)

    return (
        True,
        str(resolved_current),
        total_mix_label,
        tree_nodes,
        breadcrumbs,
        tuple(rows),
    )


async def build_library_workspace_view(
    session: AsyncSession,
    *,
    comics_dir: Path | None,
    browse_path: str | None,
    browser_sort: str,
    total_files: int,
    matched_files: int,
    unmatched_files: int,
    total_size_bytes: int,
    format_counts: Mapping[str, int],
) -> LibraryWorkspaceView:
    """Build the prototype-aligned library shell presenter."""
    enabled_roots = list(
        (
            await session.execute(
                select(LibraryRoot).where(LibraryRoot.enabled.is_(True)).order_by(LibraryRoot.id)
            )
        ).scalars()
    )
    root_candidates = [Path(root.path) for root in enabled_roots]
    current_path, active_root = library_clamp_browse_path(
        browse_path,
        allowed_roots=root_candidates,
        default_root=comics_dir,
    )
    normalized_browser_sort = normalize_library_browser_sort(browser_sort)
    root_path = active_root

    series_count_stmt = select(func.count(Series.id)).where(Series.path.is_not(None))
    if root_path is not None:
        root_prefix = root_path.as_posix().rstrip("/")
        series_count_stmt = series_count_stmt.where(
            or_(
                Series.path == root_prefix,
                Series.path.like(f"{root_prefix}/%"),
            )
        )
    series_count = int((await session.execute(series_count_stmt)).scalar_one() or 0)

    cbz_count = int(format_counts.get("cbz", 0))
    match_rate = (matched_files / total_files) if total_files > 0 else 0.0
    cbz_coverage = (cbz_count / total_files) if total_files > 0 else 0.0
    avg_issue_size = int(total_size_bytes / total_files) if total_files > 0 else 0

    disk_free_bytes = 0
    if root_path is not None and root_path.exists():
        try:
            usage = await asyncio.to_thread(shutil.disk_usage, root_path)
            disk_free_bytes = int(usage.free)
        except OSError:
            disk_free_bytes = 0

    series_metrics = await load_library_series_preview_metrics(session, root_path)
    snapshot = await asyncio.to_thread(
        build_library_browser_snapshot,
        current_path,
        active_root=root_path,
        library_roots=enabled_roots,
        series_metrics=series_metrics,
        total_size_bytes=total_size_bytes,
        browser_sort=normalized_browser_sort,
    )
    (
        root_available,
        current_path_label,
        root_summary_label,
        tree_nodes,
        breadcrumbs,
        browser_rows,
    ) = snapshot

    format_pills = tuple(
        LibraryFormatPillView(
            key=fmt,
            label=f".{fmt}",
            count=count,
            tone=library_format_pill_tone(fmt),
        )
        for fmt, count in sorted(format_counts.items(), key=lambda item: (-item[1], item[0]))
    )

    gauges = (
        LibraryGaugeView(
            key="files",
            label="Total Files",
            value_label=(
                f"{total_files:,}" if total_files < 10000 else f"{(total_files / 1000):.1f}k"
            ),
            tone="info",
            stroke_offset=_gauge_offset(1.0 if total_files > 0 else 0.0),
        ),
        LibraryGaugeView(
            key="series",
            label="Series",
            value_label=f"{series_count:,}",
            tone="neutral",
            stroke_offset=_gauge_offset(1.0 if series_count > 0 else 0.0),
        ),
        LibraryGaugeView(
            key="matched",
            label="Matched",
            value_label=(
                f"{matched_files:,}" if matched_files < 10000 else f"{(matched_files / 1000):.1f}k"
            ),
            tone="success",
            stroke_offset=_gauge_offset(match_rate),
        ),
        LibraryGaugeView(
            key="unmatched",
            label="Unmatched",
            value_label=f"{unmatched_files:,}",
            tone="warning" if unmatched_files > 0 else "neutral",
            stroke_offset=_gauge_offset(
                min(unmatched_files / max(total_files, 1), 1.0) if total_files > 0 else 0.0
            ),
        ),
    )

    stats = (
        LibraryStatStripItemView(
            key="storage-used",
            label="Storage Used",
            value_label=_filesize(total_size_bytes),
            tone=library_stat_tone("storage-used"),
        ),
        LibraryStatStripItemView(
            key="cbz-coverage",
            label="CBZ Coverage",
            value_label=f"{cbz_coverage * 100:.1f}%",
            tone=library_stat_tone("cbz-coverage"),
        ),
        LibraryStatStripItemView(
            key="match-rate",
            label="Match Rate",
            value_label=f"{match_rate * 100:.1f}%",
            tone=library_stat_tone("match-rate"),
        ),
        LibraryStatStripItemView(
            key="avg-issue",
            label="Avg Issue",
            value_label=_filesize(avg_issue_size) if avg_issue_size > 0 else "—",
            tone=library_stat_tone("avg-issue"),
        ),
        LibraryStatStripItemView(
            key="disk-free",
            label="Disk Free",
            value_label=_filesize(disk_free_bytes) if disk_free_bytes > 0 else "—",
            tone=library_stat_tone("disk-free"),
        ),
    )

    subtitle = (
        f"{total_files:,} files · {series_count:,} series · {_filesize(total_size_bytes)}"
        if root_path is not None
        else "No library root configured"
    )
    browser_empty_title, browser_empty_copy = library_browser_empty_state(
        root_path=root_path,
        current_path=current_path,
        root_available=root_available,
    )

    return LibraryWorkspaceView(
        root_configured=root_path is not None,
        root_available=root_available,
        subtitle=subtitle,
        root_path=str(root_path) if root_path is not None else None,
        current_path=current_path_label if current_path is not None else None,
        root_name=(root_path.name if root_path is not None and root_path.name else "library"),
        root_summary_label=root_summary_label,
        browser_sort=normalized_browser_sort,
        parent_href=(
            library_href(current_path.parent, normalized_browser_sort)
            if current_path is not None and root_path is not None and current_path != root_path
            else ""
        ),
        gauges=gauges,
        stats=stats,
        format_pills=format_pills,
        tree_nodes=tree_nodes,
        breadcrumbs=breadcrumbs,
        browser_rows=browser_rows,
        browser_empty_title=browser_empty_title,
        browser_empty_copy=browser_empty_copy,
        footer_size_label=_filesize(total_size_bytes),
        footer_free_label=_filesize(disk_free_bytes) if disk_free_bytes > 0 else "—",
    )


@router.get("/library", response_class=HTMLResponse, include_in_schema=False)
async def library(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    path: str | None = Query(None),
    sort: str = Query("name"),
) -> Response:
    """Render the library page with read-only stats."""
    from pullbox.services.library_service import get_comics_directory

    comics_dir = await get_comics_directory(session)
    if comics_dir is None:
        fallback_root = await session.scalar(
            select(LibraryRoot.path).where(LibraryRoot.enabled.is_(True)).order_by(LibraryRoot.id)
        )
        if fallback_root:
            comics_dir = Path(fallback_root)

    configs = await _system_config_values(
        session,
        [
            "series_folder_template",
            "comic_file_template",
            "annual_file_template",
            "non_standard_file_template",
            "single_non_standard_file_template",
            "replace_illegal_characters",
            "colon_replacement",
            "utility_trash_folder",
        ],
    )
    rename_templates = _rename_templates(configs)
    utility_browse_paths = _utility_browse_paths(configs)

    total_files: int = (await session.execute(select(func.count(LibraryFile.id)))).scalar_one()

    matched_files: int = (
        await session.execute(
            select(func.count(LibraryFile.id)).where(
                LibraryFile.match_confidence != MatchConfidence.UNMATCHED
            )
        )
    ).scalar_one()

    unmatched_files = total_files - matched_files

    total_size_bytes: int = (
        await session.execute(select(func.coalesce(func.sum(LibraryFile.file_size), 0)))
    ).scalar_one()

    format_counts: dict[str, int] = {}
    for fmt in FileFormat:
        count: int = (
            await session.execute(
                select(func.count(LibraryFile.id)).where(LibraryFile.file_format == fmt)
            )
        ).scalar_one()
        if count > 0:
            format_counts[fmt.value] = count

    library_view = await build_library_workspace_view(
        session,
        comics_dir=comics_dir,
        browse_path=path,
        browser_sort=sort,
        total_files=total_files,
        matched_files=matched_files,
        unmatched_files=unmatched_files,
        total_size_bytes=total_size_bytes,
        format_counts=format_counts,
    )

    return _templates().TemplateResponse(
        request,
        "pages/library.html",
        _ctx(
            request,
            user,
            comics_directory=str(comics_dir) if comics_dir else None,
            total_files=total_files,
            matched_files=matched_files,
            unmatched_files=unmatched_files,
            total_size_bytes=total_size_bytes,
            format_counts=format_counts,
            library_view=library_view,
            rename_templates=rename_templates,
            utility_trash_folder=utility_browse_paths["trash_folder"],
        ),
    )
