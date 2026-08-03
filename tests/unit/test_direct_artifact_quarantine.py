"""Quarantine lifecycle and safety tests for direct artifacts."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pullbox.core.file_safety import FileSafetyError
from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.services.direct_artifact_quarantine import (
    DirectArtifactQuarantine,
    DirectArtifactValidationError,
    validate_direct_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_cbz(path: Path, *, entry: str = "001.jpg") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry, b"synthetic image fixture")


def test_quarantine_uses_private_deterministic_attempt_paths(tmp_path: Path) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")

    workspace = quarantine.prepare(acquisition_id=12, artifact_id=34)

    assert workspace.root == (tmp_path / "direct").resolve()
    assert workspace.directory == workspace.root / "attempt-12" / "artifact-34"
    assert workspace.partial_path == workspace.directory / "payload.part"
    assert workspace.directory.stat().st_mode & 0o777 == 0o700


def test_quarantine_finalizes_from_content_not_misleading_filename(tmp_path: Path) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")
    workspace = quarantine.prepare(acquisition_id=1, artifact_id=2)
    _write_cbz(workspace.partial_path)

    final_path = quarantine.finalize(
        workspace,
        filename_hint="mislabelled-release.cbr",
    )

    assert final_path == workspace.directory / "artifact-2.cbz"
    assert final_path.is_file()
    assert not workspace.partial_path.exists()


@pytest.mark.asyncio
async def test_direct_artifact_reuses_existing_safety_and_integrity_checks(
    tmp_path: Path,
) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")
    workspace = quarantine.prepare(acquisition_id=1, artifact_id=2)
    _write_cbz(workspace.partial_path)
    final_path = quarantine.finalize(workspace, filename_hint="issue.cbz")
    session = AsyncMock()
    session.get.return_value = None

    result = await validate_direct_artifact(session, final_path)

    assert result.page_count == 1
    assert result.file_size == final_path.stat().st_size
    assert result.file_hash


@pytest.mark.asyncio
async def test_direct_artifact_rejects_archive_traversal_and_stays_quarantined(
    tmp_path: Path,
) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")
    workspace = quarantine.prepare(acquisition_id=1, artifact_id=2)
    _write_cbz(workspace.partial_path, entry="../escape.jpg")
    final_path = quarantine.finalize(workspace, filename_hint="issue.cbz")
    session = AsyncMock()
    session.get.return_value = None

    with pytest.raises(DirectArtifactValidationError) as caught:
        await validate_direct_artifact(session, final_path)

    assert caught.value.failure_class is DirectArtifactFailureClass.SAFETY
    assert caught.value.intervention is False
    assert final_path.exists()
    assert not (tmp_path / "escape.jpg").exists()


@pytest.mark.asyncio
async def test_direct_artifact_marks_resource_limit_as_overrideable_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")
    workspace = quarantine.prepare(acquisition_id=1, artifact_id=2)
    _write_cbz(workspace.partial_path)
    final_path = quarantine.finalize(workspace, filename_hint="issue.cbz")
    session = AsyncMock()
    session.get.return_value = None

    def reject_oversized_archive(*_args: object, **_kwargs: object) -> None:
        raise FileSafetyError(
            "Archive decompressed size (4,248,234,210 bytes) exceeds limit (2,097,152,000 bytes)"
        )

    monkeypatch.setattr(
        "pullbox.services.direct_artifact_quarantine.run_safety_checks",
        reject_oversized_archive,
    )

    with pytest.raises(DirectArtifactValidationError) as caught:
        await validate_direct_artifact(session, final_path)

    assert caught.value.code == "artifact_resource_safety_review"
    assert caught.value.intervention is True
    assert caught.value.overrideable is True
    assert caught.value.safety_block == {
        "kind": "archive_decompressed_size",
        "reason": (
            "Archive decompressed size (4,248,234,210 bytes) exceeds limit (2,097,152,000 bytes)"
        ),
        "details": [],
        "source": "file_safety",
        "overrideable": True,
    }


def test_quarantine_rejects_unknown_payload_and_cleans_owned_workspace(
    tmp_path: Path,
) -> None:
    quarantine = DirectArtifactQuarantine(tmp_path / "direct")
    workspace = quarantine.prepare(acquisition_id=1, artifact_id=2)
    workspace.partial_path.write_bytes(b"not a comic")

    with pytest.raises(DirectArtifactValidationError) as caught:
        quarantine.finalize(workspace, filename_hint="payload.bin")

    assert caught.value.code == "artifact_file_type_unsupported"
    quarantine.cleanup(workspace)
    assert not workspace.directory.exists()


def test_quarantine_rejects_symlinked_attempt_directory(tmp_path: Path) -> None:
    root = tmp_path / "direct"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "attempt-1").symlink_to(outside, target_is_directory=True)
    quarantine = DirectArtifactQuarantine(root)

    with pytest.raises(DirectArtifactValidationError) as caught:
        quarantine.prepare(acquisition_id=1, artifact_id=2)

    assert caught.value.code == "unsafe_quarantine_destination"
