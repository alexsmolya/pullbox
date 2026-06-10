"""Unit tests for Step 4 active file progress math."""

from __future__ import annotations

from dataclasses import dataclass

from pullbox.services.import_active_file_progress import (
    ActiveFileProgressSettings,
    active_file_progress_pct,
    calculate_import_file_progress_pct,
)


@dataclass(frozen=True)
class _ImportFileStub:
    file_path: str


def test_public_calculator_uses_stage_plan_for_archive_conversion() -> None:
    imp_file = _ImportFileStub(file_path="/imports/Archive.cbr")

    extracting = calculate_import_file_progress_pct(
        move_to_library=True,
        convert_to_preferred_format=True,
        update_embedded_comicinfo_from_match=True,
        imp_file=imp_file,
        stage="extracting",
        current=1,
        total=2,
    )
    packing = calculate_import_file_progress_pct(
        move_to_library=True,
        convert_to_preferred_format=True,
        update_embedded_comicinfo_from_match=True,
        imp_file=imp_file,
        stage="packing",
        current=1,
        total=1,
    )

    assert 0 < extracting < packing < 100


def test_rewriting_stays_below_complete_until_finalizing() -> None:
    settings = ActiveFileProgressSettings(
        move_to_library=True,
        convert_to_preferred_format=True,
        update_embedded_comicinfo_from_match=True,
    )
    imp_file = _ImportFileStub(file_path="/imports/Issue.cbz")

    rewriting_pct = active_file_progress_pct(settings, imp_file, "rewriting", 1, 1)
    finalizing_pct = active_file_progress_pct(settings, imp_file, "finalizing", 1, 1)

    assert rewriting_pct < 100
    assert finalizing_pct == 100


def test_pdf_rendering_and_encoding_progress_is_monotonic_for_page_chunks() -> None:
    settings = ActiveFileProgressSettings(
        move_to_library=True,
        convert_to_preferred_format=True,
        update_embedded_comicinfo_from_match=True,
    )
    imp_file = _ImportFileStub(file_path="/imports/Oversized.pdf")

    progress = [
        active_file_progress_pct(settings, imp_file, "rendering", 1, 675),
        active_file_progress_pct(settings, imp_file, "encoding", 1, 675),
        active_file_progress_pct(settings, imp_file, "rendering", 2, 675),
        active_file_progress_pct(settings, imp_file, "encoding", 2, 675),
        active_file_progress_pct(settings, imp_file, "rendering", 100, 675),
        active_file_progress_pct(settings, imp_file, "encoding", 100, 675),
    ]

    assert progress == sorted(progress)
    assert progress[-1] < 100
