"""Tests for import library-file registration adapter construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_import_registration_adapters_forward_callbacks_and_record_timings(
    tmp_path: Path,
) -> None:
    from pullbox.services.import_file_registration_adapters import (
        build_import_library_file_adapters,
    )

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source-bytes")
    target = tmp_path / "target.cbz"
    converted = tmp_path / "converted.cbz"
    converted.write_bytes(b"converted")
    progress_callback = AsyncMock()
    transfer_progress_callback = AsyncMock()
    observed: dict[str, Any] = {}
    clock_values = iter([1.0, 1.25, 2.0, 2.5, 4.0, 4.75])

    async def fake_convert_file(
        session: object,
        job: object,
        convert_source: Path,
        target_format: str,
        *,
        destination: Path | None = None,
        progress_callback: object | None = None,
    ) -> Path:
        observed["convert"] = (
            session,
            job,
            convert_source,
            target_format,
            destination,
            progress_callback,
        )
        return converted

    async def fake_embed_comicinfo(
        session: object,
        job: object,
        artifact_path: Path,
        payload: dict[str, Any],
        *,
        progress_callback: object | None = None,
    ) -> bool:
        observed["embed"] = (session, job, artifact_path, payload, progress_callback)
        artifact_path.write_bytes(b"embedded")
        return True

    async def fake_transfer_artifact(
        session: object,
        job: object,
        artifact_source: Path,
        artifact_target: Path,
        transfer_method: str,
        *,
        transfer_progress_callback: object | None = None,
    ) -> Path:
        observed["transfer"] = (
            session,
            job,
            artifact_source,
            artifact_target,
            transfer_method,
            transfer_progress_callback,
        )
        artifact_target.write_bytes(b"transferred")
        return artifact_target

    async def fake_materialize(
        session: object,
        job: object,
        artifact_source: Path,
        artifact_target: Path,
        payload: dict[str, Any],
        *,
        transfer_method: str,
        progress_callback: object | None = None,
    ) -> bool:
        observed["materialize"] = (
            session,
            job,
            artifact_source,
            artifact_target,
            payload,
            transfer_method,
            progress_callback,
        )
        artifact_target.write_bytes(b"materialized")
        return True

    session = object()
    job = object()
    adapters = build_import_library_file_adapters(
        session=session,
        job=job,
        convert_file_interruptible=fake_convert_file,
        embed_comicinfo_interruptible=fake_embed_comicinfo,
        transfer_artifact_interruptible=fake_transfer_artifact,
        materialize_cbz_with_comicinfo_interruptible=fake_materialize,
        clock=lambda: next(clock_values),
    )

    assert (
        await adapters.converter(
            source,
            "cbz",
            destination=tmp_path,
            progress_callback=progress_callback,
        )
        == converted
    )
    assert (
        await adapters.artifact_transfer(
            source,
            target,
            "move",
            transfer_progress_callback=transfer_progress_callback,
        )
        == target
    )
    assert (
        await adapters.comicinfo_materializer(
            source,
            target,
            {"Series": "Progress"},
            transfer_method="move",
            progress_callback=progress_callback,
        )
        is True
    )
    assert (
        await adapters.comicinfo_embedder(
            target,
            {"Series": "Progress"},
            progress_callback=progress_callback,
        )
        is True
    )

    assert observed["convert"][-1] is progress_callback
    assert observed["transfer"][-1] is transfer_progress_callback
    assert observed["materialize"][-1] is progress_callback
    assert observed["embed"][-1] is progress_callback
    assert [timing["kind"] for timing in adapters.operation_timings] == [
        "transfer",
        "cbz_comicinfo_materialize",
        "comicinfo_rewrite",
    ]
    assert adapters.operation_timings[0]["target_size_bytes"] == len(b"transferred")
    assert adapters.operation_timings[1]["target_size_bytes"] == len(b"materialized")
    assert adapters.operation_timings[2]["changed"] is True
    assert adapters.operation_timings[0]["duration_ms"] == 250
