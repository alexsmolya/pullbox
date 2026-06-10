"""Tests for library presenter and browser helper contracts."""

from __future__ import annotations

from datetime import UTC, datetime


def test_library_format_mix_sort_and_href_helpers() -> None:
    from pullbox.ui.library_presenters import (
        library_file_format_label,
        library_file_type_tone,
        library_format_pill_tone,
        library_href,
        library_is_convertible_file_format,
        library_mix_label,
        library_stat_tone,
        normalize_library_browser_sort,
    )

    assert library_format_pill_tone("cbz") == "info"
    assert library_format_pill_tone("weird") == "neutral"
    assert library_stat_tone("match-rate") == "success"
    assert library_stat_tone("other") == "default"
    assert library_file_type_tone("PDF") == "warning"
    assert library_file_type_tone("Folder") == "neutral"
    assert library_file_format_label("Batman 001.cbz") == "CBZ"
    assert library_file_format_label("README") is None
    assert library_is_convertible_file_format("cbr") is True
    assert library_is_convertible_file_format("PDF") is True
    assert library_is_convertible_file_format("cbz") is False
    assert library_mix_label(1, 1) == "1 folder · 1 file"
    assert library_mix_label(2, 3) == "2 folders · 3 files"
    assert library_mix_label(0, 0) == "No entries yet"
    assert normalize_library_browser_sort("-size") == "-size"
    assert normalize_library_browser_sort("nonsense") == "name"
    assert library_href() == "/library"
    assert library_href("/comics/A B", "-modified") == (
        "/library?path=%2Fcomics%2FA+B&sort=-modified"
    )


def test_library_path_clamping_and_empty_state_copy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.library_presenters import (
        library_browser_empty_state,
        library_clamp_browse_path,
    )

    root = tmp_path / "comics"
    child = root / "Batman"
    outside = tmp_path / "outside"
    child.mkdir(parents=True)
    outside.mkdir()

    current_path, active_root = library_clamp_browse_path(
        str(child),
        allowed_roots=[root],
        default_root=root,
    )
    assert current_path == child.resolve()
    assert active_root == root.resolve()

    fallback_path, fallback_root = library_clamp_browse_path(
        str(outside),
        allowed_roots=[root],
        default_root=root,
    )
    assert fallback_path == root.resolve()
    assert fallback_root == root.resolve()

    assert library_browser_empty_state(
        root_path=root,
        current_path=child,
        root_available=True,
    ) == (
        "Folder is empty",
        "This folder does not contain any visible files or subfolders yet.",
    )
    assert (
        library_browser_empty_state(
            root_path=root,
            current_path=root,
            root_available=False,
        )[0]
        == "Configured root is unavailable"
    )


def test_library_browser_sort_value_uses_typed_fields() -> None:
    from pullbox.ui.library_presenters import (
        LibraryBrowserRowView,
        LibraryBrowserSortableRow,
        library_browser_sort_value,
    )

    modified = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    row = LibraryBrowserSortableRow(
        group=0,
        name="batman",
        items=42,
        size=1234,
        type="folder",
        modified=modified,
        row=LibraryBrowserRowView(
            key="row-1",
            name="Batman",
            path="/comics/Batman",
            kind="folder",
            root_path="/comics",
            is_folder=True,
            file_format=None,
            is_convertible=False,
            href="/library?path=/comics/Batman",
            item_count_label="42",
            size_label="1.2 KB",
            type_label="Folder",
            type_tone="neutral",
            modified_label="Now",
        ),
    )

    assert library_browser_sort_value(row, "items") == 42
    assert library_browser_sort_value(row, "size") == 1234
    assert library_browser_sort_value(row, "type") == "folder"
    assert library_browser_sort_value(row, "modified") == modified
    assert library_browser_sort_value(row, "name") == "batman"
