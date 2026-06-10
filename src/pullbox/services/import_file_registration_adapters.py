"""Adapter construction for import library-file registration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    ProgressCallback = Callable[[str, int, int, str], Awaitable[None] | None]


@dataclass(frozen=True)
class ImportLibraryFileAdapters:
    """Registration callbacks plus operation timings collected by those callbacks."""

    converter: Any
    comicinfo_embedder: Any
    artifact_transfer: Any
    comicinfo_materializer: Any
    operation_timings: list[dict[str, Any]]


def build_import_library_file_adapters(
    *,
    session: Any,
    job: Any,
    convert_file_interruptible: Any,
    embed_comicinfo_interruptible: Any,
    transfer_artifact_interruptible: Any,
    materialize_cbz_with_comicinfo_interruptible: Any,
    clock: Callable[[], float] = time.monotonic,
) -> ImportLibraryFileAdapters:
    """Build interruptible register_library_file adapters for import execution."""
    operation_timings: list[dict[str, Any]] = []

    async def convert_import_file(
        convert_source: Path,
        target_format: str,
        destination: Path | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        return cast(
            "Path",
            await convert_file_interruptible(
                session,
                job,
                convert_source,
                target_format,
                destination=destination,
                progress_callback=progress_callback,
            ),
        )

    async def embed_import_comicinfo(
        artifact_path: Path,
        payload: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> bool:
        started_at = clock()
        result = bool(
            await embed_comicinfo_interruptible(
                session,
                job,
                artifact_path,
                payload,
                progress_callback=progress_callback,
            )
        )
        operation_timings.append(
            {
                "kind": "comicinfo_rewrite",
                "artifact_path": str(artifact_path),
                "artifact_file_name": artifact_path.name,
                "artifact_size_bytes": artifact_path.stat().st_size
                if artifact_path.exists()
                else None,
                "duration_ms": round((clock() - started_at) * 1000),
                "changed": result,
            }
        )
        return result

    async def transfer_import_artifact(
        artifact_source: Path,
        artifact_target: Path,
        transfer_method: str,
        **transfer_kwargs: Any,
    ) -> Path:
        transfer_progress_callback = transfer_kwargs.get("transfer_progress_callback")
        source_size = artifact_source.stat().st_size if artifact_source.exists() else None
        started_at = clock()
        result = cast(
            "Path",
            await transfer_artifact_interruptible(
                session,
                job,
                artifact_source,
                artifact_target,
                transfer_method,
                transfer_progress_callback=transfer_progress_callback
                if callable(transfer_progress_callback)
                else None,
            ),
        )
        operation_timings.append(
            {
                "kind": "transfer",
                "source_path": str(artifact_source),
                "target_path": str(artifact_target),
                "target_file_name": artifact_target.name,
                "transfer_method": transfer_method,
                "source_size_bytes": source_size,
                "target_size_bytes": result.stat().st_size if result.exists() else None,
                "duration_ms": round((clock() - started_at) * 1000),
            }
        )
        return result

    async def materialize_import_cbz_with_comicinfo(
        artifact_source: Path,
        artifact_target: Path,
        payload: dict[str, Any],
        *,
        transfer_method: str,
        progress_callback: ProgressCallback | None = None,
    ) -> bool:
        source_size = artifact_source.stat().st_size if artifact_source.exists() else None
        started_at = clock()
        result = bool(
            await materialize_cbz_with_comicinfo_interruptible(
                session,
                job,
                artifact_source,
                artifact_target,
                payload,
                transfer_method=transfer_method,
                progress_callback=progress_callback,
            )
        )
        operation_timings.append(
            {
                "kind": "cbz_comicinfo_materialize",
                "source_path": str(artifact_source),
                "target_path": str(artifact_target),
                "target_file_name": artifact_target.name,
                "transfer_method": transfer_method,
                "source_size_bytes": source_size,
                "target_size_bytes": artifact_target.stat().st_size
                if artifact_target.exists()
                else None,
                "duration_ms": round((clock() - started_at) * 1000),
                "changed": result,
            }
        )
        return result

    return ImportLibraryFileAdapters(
        converter=convert_import_file,
        comicinfo_embedder=embed_import_comicinfo,
        artifact_transfer=transfer_import_artifact,
        comicinfo_materializer=materialize_import_cbz_with_comicinfo,
        operation_timings=operation_timings,
    )
