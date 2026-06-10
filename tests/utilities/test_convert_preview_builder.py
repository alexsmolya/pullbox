"""Tests for converter preview builder helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.utilities.preview_builders import build_convert_preview_response
from pullbox.utilities.schemas import ConvertPreviewRequest

if TYPE_CHECKING:
    from pathlib import Path


def test_convert_preview_builder_delegates_manual_file_preview(tmp_path: Path) -> None:
    first = tmp_path / "Batman 001.cbr"
    second = tmp_path / "Batman 002.cbr"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    preview = build_convert_preview_response(
        ConvertPreviewRequest(
            source_format="cbr",
            target_format="cbz",
            scope="manual",
            file_paths=[str(first), str(second)],
        )
    )

    assert preview.source_format == "cbr"
    assert preview.target_format == "cbz"
    assert preview.lossless is True
    assert preview.total_count == 2
    assert preview.total_size_bytes == first.stat().st_size + second.stat().st_size
    assert [file.output_path for file in preview.files] == [
        str(first.with_suffix(".cbz")),
        str(second.with_suffix(".cbz")),
    ]
