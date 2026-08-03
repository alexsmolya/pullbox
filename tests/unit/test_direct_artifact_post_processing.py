"""Adapter tests for handing direct artifacts to existing post-processing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from pullbox.services.direct_artifact_post_processing import (
    run_direct_artifact_post_processing,
)


@pytest.mark.asyncio
async def test_direct_handoff_reuses_pipeline_without_client_mapping_or_cleanup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "quarantine" / "artifact-2.cbz"
    source.parent.mkdir()
    source.write_bytes(b"fixture")
    session = AsyncMock()
    library_file = SimpleNamespace(id=77, file_path="/library/Series/Issue 1.cbz")
    query_result = SimpleNamespace(scalar_one_or_none=lambda: library_file)
    session.execute.return_value = query_result
    observed: dict[str, Any] = {}

    async def fake_post_processor(
        session: Any,
        download: Any,
        *,
        resolve_local_path: Any,
        cleanup_source: bool,
        allow_resource_safety_exception: bool,
    ) -> None:
        observed["session"] = session
        observed["download"] = download
        observed["cleanup_source"] = cleanup_source
        observed["allow_resource_safety_exception"] = allow_resource_safety_exception
        observed["resolved_path"] = await resolve_local_path(session, download)
        download.final_path = library_file.file_path

    result = await run_direct_artifact_post_processing(
        session,
        acquisition_id=12,
        issue_id=34,
        source_path=source,
        replace_existing_file=True,
        allow_resource_safety_exception=True,
        post_processor=fake_post_processor,
    )

    assert observed["session"] is session
    assert observed["cleanup_source"] is False
    assert observed["allow_resource_safety_exception"] is True
    assert observed["resolved_path"] == str(source)
    assert observed["download"].id == -12
    assert observed["download"].download_client.value == "direct"
    assert observed["download"].replace_existing_file is True
    assert result.library_file_id == 77
    assert result.final_path == Path(library_file.file_path)


@pytest.mark.asyncio
async def test_direct_handoff_fails_when_pipeline_does_not_register_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "artifact.cbz"
    source.write_bytes(b"fixture")
    session = AsyncMock()
    query_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    session.execute.return_value = query_result

    async def no_op_post_processor(*_args: Any, **_kwargs: Any) -> None:
        return None

    with pytest.raises(RuntimeError, match="did not register"):
        await run_direct_artifact_post_processing(
            session,
            acquisition_id=1,
            issue_id=2,
            source_path=source,
            replace_existing_file=False,
            post_processor=no_op_post_processor,
        )


@pytest.mark.asyncio
async def test_direct_handoff_materializes_library_symlink_before_quarantine_cleanup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "quarantine" / "artifact-2.cbz"
    source.parent.mkdir()
    source.write_bytes(b"direct artifact")
    library_path = tmp_path / "library" / "Issue 1.cbz"
    library_path.parent.mkdir()
    session = AsyncMock()
    library_file = SimpleNamespace(id=77, file_path=str(library_path))
    session.execute.return_value = SimpleNamespace(
        scalar_one_or_none=lambda: library_file,
    )

    async def symlink_post_processor(
        _session: Any,
        download: Any,
        **_kwargs: Any,
    ) -> None:
        library_path.symlink_to(source)
        download.final_path = str(library_path)

    result = await run_direct_artifact_post_processing(
        session,
        acquisition_id=12,
        issue_id=34,
        source_path=source,
        replace_existing_file=False,
        post_processor=symlink_post_processor,
    )

    assert result.final_path == library_path
    assert library_path.is_symlink() is False
    assert library_path.read_bytes() == b"direct artifact"
    assert source.exists()
