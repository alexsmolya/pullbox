"""Focused tests for the library browser presenter."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pullbox.models.library import LibraryRoot
from pullbox.ui.routes import _build_library_browser_snapshot, _library_browser_empty_state

if TYPE_CHECKING:
    from pathlib import Path


def _flatten_tree_names(nodes: tuple[object, ...]) -> list[str]:
    names: list[str] = []
    for node in nodes:
        names.append(node.name)
        names.extend(_flatten_tree_names(node.children))
    return names


def test_library_browser_snapshot_returns_all_visible_entries(tmp_path: Path) -> None:
    """The browser presenter should not silently cap tree or row entries."""
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()

    for index in range(20):
        (library_root_path / f"{index:02d}-series").mkdir()
        (library_root_path / f"{index:02d}-issue.cbz").write_text("test", encoding="utf-8")

    hidden_dir = library_root_path / ".hidden"
    hidden_dir.mkdir()
    (library_root_path / ".hidden.cbz").write_text("hidden", encoding="utf-8")

    root = LibraryRoot(name="Primary", path=str(library_root_path), enabled=True)

    (
        root_available,
        current_path_label,
        _summary_label,
        tree_nodes,
        breadcrumbs,
        rows,
    ) = _build_library_browser_snapshot(
        library_root_path,
        active_root=library_root_path,
        library_roots=[root],
        series_metrics={},
        total_size_bytes=0,
        browser_sort="name",
    )

    assert root_available is True
    assert current_path_label == str(library_root_path)
    assert len(tree_nodes) == 1
    assert tree_nodes[0].has_children is True
    assert len(tree_nodes[0].children) == 20
    assert len(rows) == 40
    assert len(breadcrumbs) == 1
    assert tree_nodes[0].kind == "root"
    assert tree_nodes[0].is_root is True
    assert rows[0].root_path == str(library_root_path)
    assert all(".hidden" not in name for name in _flatten_tree_names(tree_nodes))
    assert all(".hidden" not in row.name for row in rows)


def test_library_browser_snapshot_marks_active_branch_open(tmp_path: Path) -> None:
    """The active branch should stay expanded in the nested tree."""
    library_root_path = tmp_path / "library"
    root_folder = library_root_path / "batman"
    issue_folder = root_folder / "year-one"
    issue_folder.mkdir(parents=True)

    root = LibraryRoot(name="Primary", path=str(library_root_path), enabled=True)

    (
        root_available,
        _current_path_label,
        _summary_label,
        tree_nodes,
        _breadcrumbs,
        _rows,
    ) = _build_library_browser_snapshot(
        issue_folder,
        active_root=library_root_path,
        library_roots=[root],
        series_metrics={},
        total_size_bytes=0,
        browser_sort="name",
    )

    assert root_available is True
    assert tree_nodes[0].is_open is True
    assert tree_nodes[0].children[0].name == "batman"
    assert tree_nodes[0].children[0].is_open is True
    assert tree_nodes[0].children[0].children[0].name == "year-one"
    assert tree_nodes[0].children[0].children[0].is_active is True


def test_library_browser_snapshot_sorts_rows_by_size_desc(tmp_path: Path) -> None:
    """Browser sort should order rows within the pane without dropping entries."""
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()

    (library_root_path / "alpha.cbz").write_bytes(b"a")
    (library_root_path / "omega.cbz").write_bytes(b"abcde")

    root = LibraryRoot(name="Primary", path=str(library_root_path), enabled=True)

    (
        root_available,
        _current_path_label,
        _summary_label,
        _tree_nodes,
        _breadcrumbs,
        rows,
    ) = _build_library_browser_snapshot(
        library_root_path,
        active_root=library_root_path,
        library_roots=[root],
        series_metrics={},
        total_size_bytes=0,
        browser_sort="-size",
    )

    assert root_available is True
    assert [row.name for row in rows] == ["omega.cbz", "alpha.cbz"]
    assert rows[0].file_format == "CBZ"
    assert rows[0].is_convertible is False


def test_library_browser_snapshot_uses_display_datetime_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Modified labels should respect the shared display date/time settings."""
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()

    issue_file = library_root_path / "alpha.cbz"
    issue_file.write_bytes(b"abc")
    modified_at = datetime(2026, 4, 21, 15, 45, tzinfo=UTC)
    os.utime(issue_file, (modified_at.timestamp(), modified_at.timestamp()))

    monkeypatch.setattr(
        "pullbox.core.display_time.get_cached_display_settings",
        lambda: {
            "timezone": "UTC",
            "date_format": "YYYY-MM-DD",
            "time_format": "24h",
            "show_seconds": False,
            "show_timezone": False,
            "show_ampm": False,
        },
    )
    monkeypatch.setattr(
        "pullbox.core.display_time.get_display_timezone",
        lambda *, db_value="browser": ZoneInfo("UTC"),
    )

    root = LibraryRoot(name="Primary", path=str(library_root_path), enabled=True)

    (
        root_available,
        _current_path_label,
        _summary_label,
        _tree_nodes,
        _breadcrumbs,
        rows,
    ) = _build_library_browser_snapshot(
        library_root_path,
        active_root=library_root_path,
        library_roots=[root],
        series_metrics={},
        total_size_bytes=0,
        browser_sort="name",
    )

    assert root_available is True
    assert rows[0].modified_label == "2026-04-21, 15:45"


def test_library_browser_empty_state_uses_folder_copy_for_empty_subfolder(tmp_path: Path) -> None:
    """Empty subfolders should not reuse the library-root onboarding copy."""
    library_root_path = tmp_path / "library"
    empty_folder = library_root_path / "empty-folder"
    empty_folder.mkdir(parents=True)

    title, copy = _library_browser_empty_state(
        root_path=library_root_path,
        current_path=empty_folder,
        root_available=True,
    )

    assert title == "Folder is empty"
    assert copy == "This folder does not contain any visible files or subfolders yet."


def test_library_browser_empty_state_keeps_root_copy_for_empty_root(tmp_path: Path) -> None:
    """The root-level empty state should keep the onboarding guidance."""
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()

    title, copy = _library_browser_empty_state(
        root_path=library_root_path,
        current_path=library_root_path,
        root_available=True,
    )

    assert title == "Library root is empty"
    assert "Import a collection" in copy
