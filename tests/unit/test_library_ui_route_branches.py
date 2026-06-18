"""Focused branch coverage for the split library UI route module."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.ui import library_routes

if TYPE_CHECKING:
    from pathlib import Path


class RecordingTemplates:
    """Tiny templates stand-in that records the route render contract."""

    def __init__(self) -> None:
        self.env = SimpleNamespace(globals={})
        self.calls: list[tuple[str, dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette's template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        self.calls.append((template_name, context))
        return SimpleNamespace(template_name=template_name, context=context, status_code=200)


@pytest.fixture
def configured_library_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()

    async def _load_config_values(_session: object, keys: list[str]) -> dict[str, str]:
        return {key: f"config:{key}" for key in keys}

    monkeypatch.setattr(library_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        library_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    monkeypatch.setattr(
        library_routes,
        "_load_system_config_values",
        _load_config_values,
    )
    monkeypatch.setattr(
        library_routes,
        "_build_rename_templates",
        lambda configs: {
            "series": configs["series_folder_template"],
            "comic": configs["comic_file_template"],
        },
    )
    monkeypatch.setattr(
        library_routes,
        "_resolve_utility_browse_paths",
        lambda configs: {"trash_folder": configs["utility_trash_folder"]},
    )
    monkeypatch.setattr(library_routes, "_format_filesize", lambda value: f"{value} bytes")
    monkeypatch.setattr(
        library_routes,
        "_format_localtime",
        lambda value, fmt=None: value.strftime(fmt or "%Y-%m-%d") if value else "never",
    )
    monkeypatch.setattr(
        library_routes,
        "_dashboard_gauge_offset",
        lambda value: round(100.0 - (value * 100.0), 2),
    )
    return templates


@pytest.mark.parametrize(
    ("attribute", "callable_name", "error"),
    [
        ("_get_templates", "_templates", "templates"),
        ("_build_context", "_ctx", "context builder"),
        ("_load_system_config_values", "_system_config_values", "system config loader"),
        ("_build_rename_templates", "_rename_templates", "rename template builder"),
        ("_resolve_utility_browse_paths", "_utility_browse_paths", "utility path resolver"),
        ("_format_filesize", "_filesize", "filesize formatter"),
        ("_format_localtime", "_localtime", "localtime formatter"),
        ("_dashboard_gauge_offset", "_gauge_offset", "gauge helper"),
    ],
)
@pytest.mark.asyncio
async def test_library_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(library_routes, attribute, None)
    callable_obj = getattr(library_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        elif callable_name == "_system_config_values":
            await callable_obj(db_session, ["comic_file_template"])
        elif callable_name in {"_rename_templates", "_utility_browse_paths"}:
            callable_obj({})
        elif callable_name == "_localtime":
            callable_obj(None)
        elif callable_name in {"_filesize", "_gauge_offset"}:
            callable_obj(1)
        else:
            callable_obj()


def test_library_browser_snapshot_handles_missing_root(
    configured_library_routes: RecordingTemplates,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"

    available, current_path, summary, tree, breadcrumbs, rows = (
        library_routes.build_library_browser_snapshot(
            missing_root,
            active_root=missing_root,
            library_roots=[LibraryRoot(id=1, name="Main", path=str(missing_root), enabled=True)],
            series_metrics={},
            total_size_bytes=0,
            browser_sort="bogus",
        )
    )

    assert available is False
    assert current_path == str(missing_root)
    assert summary == "Configured root is unavailable"
    assert tree == ()
    assert breadcrumbs == ()
    assert rows == ()


def test_library_browser_snapshot_builds_tree_rows_and_sorting(
    configured_library_routes: RecordingTemplates,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    batman = root / "Batman"
    batman.mkdir()
    (batman / "Year One").mkdir()
    saga = root / "Saga"
    saga.mkdir()
    (root / ".hidden").mkdir()
    (root / "issue.pdf").write_bytes(b"pdf")
    (root / "notes.txt").write_text("notes")
    modified_at = datetime(2026, 1, 2, tzinfo=UTC)

    available, current_path, summary, tree, breadcrumbs, rows = (
        library_routes.build_library_browser_snapshot(
            root,
            active_root=root,
            library_roots=[
                LibraryRoot(id=1, name="Main", path=str(root), enabled=True),
                LibraryRoot(id=2, name="Disabled", path=str(tmp_path / "off"), enabled=False),
            ],
            series_metrics={str(batman): (7, 4096, modified_at)},
            total_size_bytes=4096,
            browser_sort="-size",
        )
    )

    assert available is True
    assert current_path == str(root)
    assert summary == "2 folders · 2 files"
    assert len(tree) == 1
    assert tree[0].name == "Main"
    assert tree[0].is_active is True
    assert tree[0].children[0].name == "Batman"
    assert breadcrumbs[-1].label == "library"
    assert [row.name for row in rows] == ["Batman", "Saga", "notes.txt", "issue.pdf"]
    assert rows[0].item_count_label == "7"
    assert rows[0].size_label == "4096 bytes"
    assert rows[0].modified_label == "2026-01-02"
    assert rows[3].file_format == "PDF"
    assert rows[3].is_convertible is True
    assert all(not row.name.startswith(".") for row in rows)


def test_library_browser_snapshot_handles_nested_breadcrumb_and_desc_sort(
    configured_library_routes: RecordingTemplates,
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    nested = root / "A" / "B"
    nested.mkdir(parents=True)
    (nested / "tiny.cbz").write_bytes(b"1")
    (nested / "large.cbr").write_bytes(b"12345")

    available, _current_path, summary, _tree, breadcrumbs, rows = (
        library_routes.build_library_browser_snapshot(
            nested,
            active_root=root,
            library_roots=[LibraryRoot(id=1, name="Main", path=str(root), enabled=True)],
            series_metrics={},
            total_size_bytes=6,
            browser_sort="-modified",
        )
    )

    assert available is True
    assert summary == "2 files"
    assert [crumb.label for crumb in breadcrumbs] == ["library", "A", "B"]
    assert {row.name for row in rows} == {"large.cbr", "tiny.cbz"}
    assert all(row.is_folder is False for row in rows)


@pytest.mark.asyncio
async def test_build_library_workspace_view_rolls_up_stats(
    configured_library_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "library"
    root_path.mkdir()
    series_path = root_path / "Batman"
    series_path.mkdir()
    issue_path = series_path / "Batman 001.cbz"
    issue_path.write_bytes(b"comic")
    now = datetime(2026, 1, 3, tzinfo=UTC)
    monkeypatch.setattr(
        library_routes.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=2048),
    )
    root = LibraryRoot(name="Main", path=str(root_path), enabled=True)
    series = Series(
        title="Batman",
        sort_title="Batman",
        path=str(series_path),
        library_root=root,
    )
    issue = Issue(series=series, issue_number=1, title="One", status=IssueStatus.OWNED)
    library_file = LibraryFile(
        file_path=str(issue_path),
        file_name=issue_path.name,
        file_size=1024,
        file_format=FileFormat.CBZ,
        file_modified_at=now,
        match_confidence=MatchConfidence.HIGH,
        issue=issue,
        library_root=root,
    )
    db_session.add_all([root, series, issue, library_file])
    await db_session.commit()

    view = await library_routes.build_library_workspace_view(
        db_session,
        comics_dir=root_path,
        browse_path=str(series_path),
        browser_sort="items",
        total_files=2,
        matched_files=1,
        unmatched_files=1,
        total_size_bytes=2048,
        format_counts={"cbz": 1, "pdf": 1},
    )

    assert view.root_configured is True
    assert view.root_available is True
    assert view.subtitle == "2 files · 1 series · 2048 bytes"
    assert view.parent_href.startswith("/library?")
    assert [gauge.key for gauge in view.gauges] == ["files", "series", "matched", "unmatched"]
    assert view.gauges[2].value_label == "1"
    assert view.gauges[3].tone == "warning"
    assert [stat.key for stat in view.stats] == [
        "storage-used",
        "cbz-coverage",
        "match-rate",
        "avg-issue",
        "disk-free",
    ]
    assert view.stats[1].value_label == "50.0%"
    assert view.stats[2].value_label == "50.0%"
    assert view.stats[3].value_label == "1024 bytes"
    assert view.stats[4].value_label == "2048 bytes"
    assert [pill.key for pill in view.format_pills] == ["cbz", "pdf"]
    assert view.browser_empty_title == "Folder is empty"
    assert view.footer_size_label == "2048 bytes"


@pytest.mark.asyncio
async def test_build_library_workspace_view_without_root_uses_empty_state(
    configured_library_routes: RecordingTemplates,
    db_session,
) -> None:
    view = await library_routes.build_library_workspace_view(
        db_session,
        comics_dir=None,
        browse_path=None,
        browser_sort="nope",
        total_files=0,
        matched_files=0,
        unmatched_files=0,
        total_size_bytes=0,
        format_counts={},
    )

    assert view.root_configured is False
    assert view.root_available is False
    assert view.subtitle == "No library root configured"
    assert view.browser_sort == "name"
    assert view.root_name == "library"
    assert view.parent_href == ""
    assert view.browser_empty_title == "Library root is empty"
    assert view.footer_free_label == "—"


@pytest.mark.asyncio
async def test_library_route_uses_enabled_root_fallback_and_renders_context(
    configured_library_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    tmp_path: Path,
) -> None:
    from pullbox.services import library_service

    root_path = tmp_path / "library"
    root_path.mkdir()
    issue_path = root_path / "Batman 001.cbz"
    issue_path.write_bytes(b"comic")
    now = datetime(2026, 1, 4, tzinfo=UTC)

    async def _no_configured_comics_directory(_session: object) -> None:
        return None

    monkeypatch.setattr(
        library_service,
        "get_comics_directory",
        _no_configured_comics_directory,
    )
    monkeypatch.setattr(
        library_routes.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=99),
    )
    root = LibraryRoot(name="Main", path=str(root_path), enabled=True)
    unmatched_file = LibraryFile(
        file_path=str(issue_path),
        file_name=issue_path.name,
        file_size=512,
        file_format=FileFormat.CBZ,
        file_modified_at=now,
        match_confidence=MatchConfidence.UNMATCHED,
        library_root=root,
    )
    db_session.add_all([root, unmatched_file])
    await db_session.commit()

    request = SimpleNamespace(headers={}, cookies={}, state=SimpleNamespace())
    response = await library_routes.library(
        request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        path=None,
        sort="-type",
    )

    assert response.template_name == "pages/library.html"
    assert configured_library_routes.calls[-1][0] == "pages/library.html"
    context = response.context
    assert context["comics_directory"] == str(root_path)
    assert context["total_files"] == 1
    assert context["matched_files"] == 0
    assert context["unmatched_files"] == 1
    assert context["total_size_bytes"] == 512
    assert context["format_counts"] == {"cbz": 1}
    assert context["rename_templates"] == {
        "series": "config:series_folder_template",
        "comic": "config:comic_file_template",
    }
    assert context["utility_trash_folder"] == "config:utility_trash_folder"
