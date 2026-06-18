#!/usr/bin/env python3
"""Prune oversized imported issue files while keeping series metadata intact.

The script is intentionally dry-run by default. Use --execute to unlink files
and reset their issues to SKIPPED.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

import pullbox.database  # noqa: F401 - registers SQLite connection pragmas
from pullbox.models.import_job import ImportedFile
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import LibraryFile
from pullbox.models.matching_suggestion import MatchingSuggestion

DEFAULT_DB_URL = "sqlite+aiosqlite:////data/pullbox.db"
DEFAULT_THRESHOLD_MIB = 100
BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True)
class PathMap:
    source_prefix: str
    target_prefix: Path


@dataclass
class FilePruneTarget:
    library_file: LibraryFile
    resolved_path: Path
    db_size: int
    actual_size: int | None
    effective_size: int


@dataclass
class PruneCandidate:
    issue: Issue
    files: list[FilePruneTarget]

    @property
    def effective_size(self) -> int:
        return sum(file.effective_size for file in self.files)


@dataclass
class PruneResult:
    pruned_count: int = 0
    freed_bytes: int = 0
    skipped_missing_count: int = 0
    error_count: int = 0


@dataclass
class TrashSummary:
    path: Path
    exists: bool
    file_count: int = 0
    directory_count: int = 0
    total_bytes: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete imported issue files over a size threshold and reset those "
            "issues to SKIPPED without deleting any series."
        )
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("PULLBOX_DB_URL", DEFAULT_DB_URL),
        help=(f"SQLAlchemy database URL. Defaults to PULLBOX_DB_URL or {DEFAULT_DB_URL!r}."),
    )
    parser.add_argument(
        "--threshold-mib",
        type=float,
        default=DEFAULT_THRESHOLD_MIB,
        help=f"Prune files larger than this many MiB. Default: {DEFAULT_THRESHOLD_MIB}.",
    )
    parser.add_argument(
        "--path-map",
        action="append",
        default=[],
        metavar="DB_PREFIX=HOST_PREFIX",
        help=(
            "Map database file paths to host paths when running outside the "
            "container, e.g. /comics=/Users/adam/Code/pullbox-dev/live-comics. "
            "May be supplied more than once."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete matching files and update the database.",
    )
    parser.add_argument(
        "--trash-dir",
        type=Path,
        default=None,
        help=(
            "Library trash directory to empty. Defaults to "
            "$PULLBOX_LIBRARY_ROOT/.trash or /comics/.trash."
        ),
    )
    return parser.parse_args()


def parse_path_maps(raw_values: list[str]) -> list[PathMap]:
    maps: list[PathMap] = []
    for raw_value in raw_values:
        if "=" not in raw_value:
            raise SystemExit(
                f"Invalid --path-map value {raw_value!r}; expected DB_PREFIX=HOST_PREFIX."
            )
        source, target = raw_value.split("=", 1)
        source = source.rstrip("/")
        if not source:
            raise SystemExit(f"Invalid --path-map value {raw_value!r}; DB_PREFIX cannot be empty.")
        maps.append(PathMap(source_prefix=source, target_prefix=Path(target)))
    return sorted(maps, key=lambda path_map: len(path_map.source_prefix), reverse=True)


def resolve_file_path(file_path: str, path_maps: list[PathMap]) -> Path:
    for path_map in path_maps:
        source = path_map.source_prefix
        if file_path == source:
            return path_map.target_prefix
        if file_path.startswith(f"{source}/"):
            suffix = file_path[len(source) + 1 :]
            return path_map.target_prefix / suffix
    return Path(file_path)


def resolve_trash_dir(raw_trash_dir: Path | None) -> Path:
    trash_dir = raw_trash_dir
    if trash_dir is None:
        library_root = Path(os.getenv("PULLBOX_LIBRARY_ROOT", "/comics"))
        trash_dir = library_root / ".trash"
    if trash_dir.name != ".trash":
        raise SystemExit(f"Refusing to empty {trash_dir}; trash directory must be named .trash.")
    return trash_dir


def format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    if size_bytes >= BYTES_PER_MIB:
        return f"{size_bytes / BYTES_PER_MIB:.1f} MiB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes} B"


def issue_label(issue: Issue) -> str:
    number = issue.issue_number or "unknown"
    title = f" - {issue.title}" if issue.title else ""
    return f"#{number}{title}"


def scan_trash(trash_dir: Path) -> TrashSummary:
    if not trash_dir.exists():
        return TrashSummary(path=trash_dir, exists=False)
    if trash_dir.is_symlink() or not trash_dir.is_dir():
        raise RuntimeError(f"Refusing to empty non-directory trash path {trash_dir}.")

    summary = TrashSummary(path=trash_dir, exists=True)
    for child in trash_dir.rglob("*"):
        if child.is_symlink() or child.is_file():
            summary.file_count += 1
            summary.total_bytes += child.lstat().st_size
        elif child.is_dir():
            summary.directory_count += 1
    return summary


def print_trash_summary(summary: TrashSummary, execute: bool) -> None:
    mode = "EXECUTE" if execute else "DRY RUN"
    if not summary.exists:
        print(f"{mode}: trash directory does not exist: {summary.path}")
        return
    print(
        f"{mode}: trash contains {summary.file_count} file(s), "
        f"{summary.directory_count} folder(s), {format_size(summary.total_bytes)}."
    )
    print(f"Trash path: {summary.path}")


def empty_trash(trash_dir: Path) -> TrashSummary:
    summary = scan_trash(trash_dir)
    if not summary.exists:
        return summary
    for child in trash_dir.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    return summary


async def collect_candidates(
    session_factory: async_sessionmaker,
    threshold_bytes: int,
    path_maps: list[PathMap],
) -> list[PruneCandidate]:
    async with session_factory() as session:
        result = await session.execute(
            select(LibraryFile)
            .options(selectinload(LibraryFile.issue).selectinload(Issue.series))
            .where(LibraryFile.issue_id.is_not(None))
            .order_by(LibraryFile.file_path.asc())
        )
        library_files = list(result.scalars().all())

        targets_by_issue_id: dict[int, tuple[Issue, list[FilePruneTarget]]] = {}
        for library_file in library_files:
            issue = library_file.issue
            if issue is None:
                continue
            resolved_path = resolve_file_path(library_file.file_path, path_maps)
            actual_size: int | None = None
            if resolved_path.exists() and resolved_path.is_file():
                actual_size = resolved_path.stat().st_size
            db_size = library_file.file_size or 0
            effective_size = actual_size if actual_size is not None else db_size
            targets_by_issue_id.setdefault(issue.id, (issue, []))[1].append(
                FilePruneTarget(
                    library_file=library_file,
                    resolved_path=resolved_path,
                    db_size=db_size,
                    actual_size=actual_size,
                    effective_size=effective_size,
                )
            )

        candidates = [
            PruneCandidate(issue=issue, files=files)
            for issue, files in targets_by_issue_id.values()
            if sum(file.effective_size for file in files) > threshold_bytes
        ]
        return sorted(candidates, key=lambda candidate: candidate.effective_size, reverse=True)


def print_candidates(candidates: list[PruneCandidate], threshold_bytes: int, execute: bool) -> None:
    mode = "EXECUTE" if execute else "DRY RUN"
    total_bytes = sum(candidate.effective_size for candidate in candidates)
    print(f"{mode}: found {len(candidates)} imported issue(s) over {format_size(threshold_bytes)}.")
    print(f"Estimated removable size: {format_size(total_bytes)}")
    if not candidates:
        return

    for index, candidate in enumerate(candidates, start=1):
        issue = candidate.issue
        series_title = issue.series.title if issue.series else "Unknown series"
        print(
            f"{index:>3}. {format_size(candidate.effective_size):>10} | "
            f"{series_title} {issue_label(issue)} | {len(candidate.files)} file(s)"
        )
        for file_target in candidate.files:
            print(f"     db:   {file_target.library_file.file_path}")
            if file_target.resolved_path.as_posix() != file_target.library_file.file_path:
                print(f"     disk: {file_target.resolved_path}")
            if file_target.actual_size is None:
                print("     note: file missing on disk; DB cleanup would still run")
            elif file_target.actual_size != file_target.db_size:
                print(
                    f"     note: DB size {format_size(file_target.db_size)}, "
                    f"actual size {format_size(file_target.actual_size)}"
                )


async def prune_candidates(
    session_factory: async_sessionmaker,
    candidates: list[PruneCandidate],
) -> PruneResult:
    result = PruneResult()
    for candidate in candidates:
        issue_id = candidate.issue.id
        library_file_ids = [file_target.library_file.id for file_target in candidate.files]
        freed_bytes = 0
        try:
            for file_target in candidate.files:
                if file_target.resolved_path.exists():
                    if not file_target.resolved_path.is_file():
                        raise RuntimeError(
                            f"refusing to delete non-file path {file_target.resolved_path}"
                        )
                    freed_bytes += file_target.resolved_path.stat().st_size
                    file_target.resolved_path.unlink()
                else:
                    result.skipped_missing_count += 1

            async with session_factory() as session:
                issue = await session.get(Issue, issue_id)
                if issue is not None:
                    issue.status = IssueStatus.SKIPPED
                    issue.integrity_status = "unchecked"
                    issue.integrity_checked_at = None
                    issue.integrity_details = "{}"
                await session.execute(
                    update(ImportedFile)
                    .where(ImportedFile.library_file_id.in_(library_file_ids))
                    .values(library_file_id=None)
                )
                await session.execute(
                    delete(MatchingSuggestion).where(
                        MatchingSuggestion.library_file_id.in_(library_file_ids)
                    )
                )
                library_files = (
                    await session.execute(
                        select(LibraryFile).where(LibraryFile.id.in_(library_file_ids))
                    )
                ).scalars()
                for library_file in library_files:
                    await session.delete(library_file)
                await session.commit()

            result.pruned_count += 1
            result.freed_bytes += freed_bytes
            print(f"pruned: issue {issue_id} ({len(library_file_ids)} file(s))")
        except Exception as exc:
            result.error_count += 1
            print(f"ERROR: failed to prune issue {issue_id}: {exc}")
    return result


async def async_main() -> int:
    args = parse_args()
    if args.threshold_mib <= 0:
        raise SystemExit("--threshold-mib must be greater than zero.")
    threshold_bytes = int(args.threshold_mib * BYTES_PER_MIB)
    path_maps = parse_path_maps(args.path_map)
    trash_dir = resolve_trash_dir(args.trash_dir)

    engine = create_async_engine(args.db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        candidates = await collect_candidates(session_factory, threshold_bytes, path_maps)
        trash_summary = scan_trash(trash_dir)
        print_candidates(candidates, threshold_bytes, args.execute)
        print_trash_summary(trash_summary, args.execute)
        if not args.execute:
            has_trash = trash_summary.exists and (
                trash_summary.file_count > 0 or trash_summary.directory_count > 0
            )
            if candidates or has_trash:
                print("\nNo files were deleted. Re-run with --execute to apply this cleanup.")
            return 0

        result = await prune_candidates(session_factory, candidates)
        emptied_trash = empty_trash(trash_dir)
        print(
            "\nPrune complete: "
            f"{result.pruned_count} issue(s) pruned, "
            f"{format_size(result.freed_bytes)} freed, "
            f"{result.skipped_missing_count} missing-on-disk cleanup(s), "
            f"{result.error_count} error(s)."
        )
        if emptied_trash.exists:
            print(
                "Trash emptied: "
                f"{emptied_trash.file_count} file(s), "
                f"{emptied_trash.directory_count} folder(s), "
                f"{format_size(emptied_trash.total_bytes)} removed."
            )
        else:
            print(f"Trash skipped: directory does not exist at {emptied_trash.path}.")
        return 1 if result.error_count else 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
