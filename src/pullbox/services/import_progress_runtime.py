"""Shared import progress runtime contract.

This module is intentionally small and pure: it owns display labels, phase
boundaries, current-item payload shape, elapsed-time math, and import weighting.
The orchestration services decide *when* to emit progress; this module decides
what that progress means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ProgressMode = Literal["scan", "import", "rollback"]

_PHASE_RANGES: dict[str, tuple[int, int]] = {
    "inventory": (0, 10),
    "scanning": (10, 35),
    "analyzing": (35, 45),
    "matching": (45, 80),
    "file_matching": (80, 99),
    "importing": (0, 100),
    "rollback": (0, 100),
    "review": (100, 100),
    "done": (100, 100),
}

_PHASE_LABELS: dict[str, str] = {
    "inventory": "Inventorying collection...",
    "scanning": "Scanning your collection...",
    "analyzing": "Analyzing for duplicates...",
    "matching": "Matching series against ComicVine...",
    "file_matching": "Matching files to issues...",
    "importing": "Importing series into Pullbox...",
    "rollback": "Rolling back import actions...",
    "review": "Complete",
    "done": "Run stopped",
}

_DEFAULT_MESSAGES: dict[tuple[ProgressMode, str], str] = {
    ("scan", "inventory"): "Inventorying collection...",
    ("scan", "scanning"): "Scanning files...",
    ("scan", "analyzing"): "Analyzing for duplicates...",
    ("scan", "matching"): "Matching against ComicVine...",
    ("scan", "file_matching"): "Matching files to issues...",
    ("scan", "review"): "Ready for review",
    ("import", "queued"): "Preparing the selected series for import...",
    ("import", "importing"): "Importing selected files...",
    ("import", "done"): "Import complete.",
    ("rollback", "rollback"): "Rolling back import actions...",
    ("rollback", "done"): "Import rollback completed.",
}

_STAGE_LABELS: dict[str, str] = {
    "inventory": "Inventorying files",
    "scanning": "Scanning files",
    "analyzing": "Analyzing discovered files",
    "matching": "Matching series against ComicVine",
    "rebucket": "Checking volume subtitles",
    "file_matching": "Matching files to issues",
    "metadata_fetch": "Fetching ComicVine metadata",
    "metadata_fetch_wait": "Fetching ComicVine metadata",
    "series_records": "Preparing series records",
    "cached_match": "Preparing cached ComicVine match",
    "review_group_complete": "Review group complete",
    "preparing": "Preparing file",
    "extracting": "Extracting archive",
    "rendering": "Rendering PDF pages",
    "encoding": "Encoding pages",
    "packing": "Packing CBZ",
    "comicinfo_metadata": "Preparing ComicInfo metadata",
    "transferring": "Transferring to library",
    "rewriting": "Writing ComicInfo.xml",
    "finalizing": "Finalizing imported file",
}

_METADATA_COMPONENT_WEIGHT = 2.0
_BASE_FILE_WEIGHT = 1.0
_MAX_SIZE_WEIGHT = 24.0
_CBZ_REWRITE_WEIGHT = 1.5
_ARCHIVE_CONVERSION_WEIGHT = 5.0
_PDF_CONVERSION_WEIGHT = 14.0
_TRANSFER_WEIGHT = 1.0


@dataclass(frozen=True, slots=True)
class ImportProgressSettings:
    """Settings that materially affect Step 4 file-work cost."""

    move_to_library: bool
    convert_to_preferred_format: bool
    update_embedded_comicinfo_from_match: bool


@dataclass(frozen=True, slots=True)
class ImportProgressFileProfile:
    """Minimal file facts needed for Step 4 progress weighting."""

    file_id: int | None
    file_path: str
    file_size: int | None = None


@dataclass(frozen=True, slots=True)
class ImportGroupProgressPlan:
    """Weighted progress plan for one Step 4 review group."""

    metadata_weight: float
    file_weights: tuple[tuple[int | None, float], ...]

    @property
    def total_weight(self) -> float:
        return max(
            self.metadata_weight + sum(weight for _file_id, weight in self.file_weights),
            1.0,
        )


def phase_range(phase: str) -> tuple[int, int]:
    """Return the canonical bounded progress range for a workflow phase."""
    return _PHASE_RANGES.get(phase, (0, 100))


def phase_label(phase: str) -> str:
    """Return the user-facing label for a workflow phase."""
    return _PHASE_LABELS.get(phase, "Processing...")


def default_phase_message(mode: ProgressMode, phase: str) -> str:
    """Return the default user-facing message for a workflow mode/phase pair."""
    return _DEFAULT_MESSAGES.get((mode, phase), phase_label(phase))


def stage_label(stage: str | None) -> str | None:
    """Return the user-facing current-item stage label."""
    if not stage:
        return None
    return _STAGE_LABELS.get(stage, "Processing")


def current_item_payload(
    *,
    kind: str,
    stage: str,
    name: str | None = None,
    progress_pct: int | float | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    """Build the explicit current-item payload shared by SSE and snapshots."""
    _ = name
    payload: dict[str, object] = {
        "current_item_kind": kind,
        "current_item_stage": stage,
        "current_item_stage_label": stage_label(stage),
        "current_item_progress_pct": _clamped_pct(progress_pct),
    }
    if detail is not None:
        payload["current_item_detail"] = detail
    return payload


def elapsed_seconds_since(started_at: datetime | None) -> int | None:
    """Return elapsed whole seconds for a workflow start timestamp."""
    if started_at is None:
        return None
    return max(int((datetime.now(UTC) - started_at).total_seconds()), 0)


def import_group_progress_plan(
    settings: ImportProgressSettings,
    files: list[ImportProgressFileProfile],
) -> ImportGroupProgressPlan:
    """Build a weighted Step 4 plan for one review group."""
    file_weights = tuple((file.file_id, import_file_weight(settings, file)) for file in files)
    return ImportGroupProgressPlan(
        metadata_weight=_METADATA_COMPONENT_WEIGHT,
        file_weights=file_weights,
    )


def import_file_weight(
    settings: ImportProgressSettings,
    file_profile: ImportProgressFileProfile,
) -> float:
    """Estimate relative work cost for one importable file."""
    suffix = Path(file_profile.file_path).suffix.lower()
    size_bytes = max(int(file_profile.file_size or 0), 0)
    size_weight = min(size_bytes / (64 * 1024 * 1024), _MAX_SIZE_WEIGHT)
    weight = _BASE_FILE_WEIGHT + size_weight

    needs_conversion = (
        settings.move_to_library
        and (settings.convert_to_preferred_format or settings.update_embedded_comicinfo_from_match)
        and suffix != ".cbz"
    )
    if needs_conversion and suffix == ".pdf":
        weight += _PDF_CONVERSION_WEIGHT
    elif needs_conversion:
        weight += _ARCHIVE_CONVERSION_WEIGHT

    if settings.move_to_library:
        weight += _TRANSFER_WEIGHT
    if settings.update_embedded_comicinfo_from_match:
        weight += _CBZ_REWRITE_WEIGHT
    return max(weight, 1.0)


def import_group_metadata_progress_pct(
    plan: ImportGroupProgressPlan,
    *,
    metadata_progress_pct: int | float,
) -> int:
    """Return current group progress while series metadata is being prepared."""
    completed = plan.metadata_weight * (_clamped_pct(metadata_progress_pct) / 100)
    return _clamped_pct((completed / plan.total_weight) * 100)


def import_group_file_progress_pct(
    plan: ImportGroupProgressPlan,
    *,
    file_index: int,
    current_file_pct: int | float,
) -> int:
    """Return current group progress while an importable file is being processed."""
    completed = plan.metadata_weight
    safe_index = max(file_index, 1)
    for idx, (_file_id, weight) in enumerate(plan.file_weights, start=1):
        if idx < safe_index:
            completed += weight
            continue
        if idx == safe_index:
            completed += weight * (_clamped_pct(current_file_pct) / 100)
            break
    return _clamped_pct((completed / plan.total_weight) * 100)


def weighted_import_progress_pct(
    group_weights: list[float] | tuple[float, ...],
    *,
    current_group_index: int,
    current_group_progress_pct: int | float,
) -> int:
    """Return whole-job Step 4 progress across weighted review groups."""
    if not group_weights:
        return 0
    safe_index = max(current_group_index, 0)
    total_weight = max(sum(max(weight, 1.0) for weight in group_weights), 1.0)
    completed = sum(max(weight, 1.0) for weight in group_weights[:safe_index])
    if safe_index < len(group_weights):
        completed += max(group_weights[safe_index], 1.0) * (
            _clamped_pct(current_group_progress_pct) / 100
        )
    return max(0, min(round((completed / total_weight) * 100), 99))


def _clamped_pct(value: int | float | None) -> int:
    if value is None:
        return 0
    return max(0, min(round(float(value)), 100))
