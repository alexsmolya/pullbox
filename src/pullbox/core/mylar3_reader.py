"""Mylar3 database reader for collection import.

Reads series data from a Mylar3 SQLite database (mylar.db) and converts
records to DiscoveredSeries instances, preserving ComicVine IDs for
high-confidence matching during the import identification phase.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import structlog

from pullbox.core.collection_scanner import COMIC_EXTENSIONS, DiscoveredFile, DiscoveredSeries
from pullbox.core.exceptions import MylarReadError
from pullbox.core.naming import parse_filename

logger = structlog.get_logger(__name__)


class Mylar3Reader:
    """Reads series data from a Mylar3 SQLite database.

    Extracts series records and converts them to DiscoveredSeries instances,
    preserving ComicVine IDs for high-confidence matching in ImportService.

    Args:
        db_path: Path to mylar.db file.
        path_map: Optional dict of {container_prefix: host_prefix}.
                  Applied to ComicLocation before checking disk.
    """

    MYLAR3_CV_PREFIX = "CV-"

    def __init__(
        self,
        db_path: str | Path,
        path_map: dict[str, str] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._path_map = path_map or {}

    async def read_series(self) -> list[DiscoveredSeries]:
        """Read all series from the Mylar3 database.

        Returns a list of DiscoveredSeries with mylar3_cv_id populated
        wherever a ComicVine ID exists in Mylar3.

        Raises:
            FileNotFoundError: If db_path does not exist.
            MylarReadError: If the file is not a valid Mylar3 database.
        """
        if not self._db_path.exists():
            msg = f"Mylar3 database not found: {self._db_path}"
            raise FileNotFoundError(msg)

        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> list[DiscoveredSeries]:
        """Synchronous database read — runs in a thread."""
        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.DatabaseError as exc:
            msg = f"Could not read Mylar3 database: {exc}"
            raise MylarReadError(msg) from exc

        try:
            # Verify the comics table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='comics'"
            )
            if not cursor.fetchone():
                msg = "Not a Mylar3 database: 'comics' table not found"
                raise MylarReadError(msg)

            rows = conn.execute(
                "SELECT ComicID, ComicName, ComicYear, ComicPublisher, "
                "ComicLocation, Status, Total FROM comics"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            msg = f"Could not read Mylar3 database: {exc}"
            raise MylarReadError(msg) from exc
        finally:
            conn.close()

        return self._convert_rows(rows)

    def _convert_rows(self, rows: list[sqlite3.Row]) -> list[DiscoveredSeries]:
        """Convert Mylar3 database rows to DiscoveredSeries instances."""
        results: list[DiscoveredSeries] = []
        seen_cv_ids: set[int] = set()

        for row in rows:
            cv_id = self._parse_cv_id(row["ComicID"])

            # Deduplicate by ComicVine ID
            if cv_id is not None and cv_id in seen_cv_ids:
                logger.warning(
                    "mylar3_duplicate_cv_id",
                    cv_id=cv_id,
                    series_name=row["ComicName"],
                )
                continue
            if cv_id is not None:
                seen_cv_ids.add(cv_id)

            year = self._parse_year(row["ComicYear"])
            location = row["ComicLocation"]
            file_count = self._get_file_count(location)
            has_files = file_count > 0

            # Build sample paths and DiscoveredFile objects from the location directory
            sample_paths: list[str] = []
            discovered_files: list[DiscoveredFile] = []
            resolved_location = self._resolve_location(location)
            if resolved_location:
                p = Path(resolved_location)
                if p.is_dir():
                    comic_paths = sorted(
                        f for f in p.iterdir() if f.suffix.lower() in COMIC_EXTENSIONS
                    )
                    sample_paths = [str(f) for f in comic_paths[:5]]
                    discovered_files = self._build_files(comic_paths)

            results.append(
                DiscoveredSeries(
                    raw_series_name=row["ComicName"] or "Unknown",
                    raw_year=year,
                    raw_publisher=row["ComicPublisher"],
                    file_count=len(discovered_files) if discovered_files else file_count,
                    sample_paths=sample_paths,
                    source_folder=resolved_location or "",
                    source_folder_relative=location or "",
                    has_files=has_files,
                    files=discovered_files,
                    mylar3_cv_id=cv_id,
                )
            )

        logger.info(
            "mylar3_read_completed",
            total_series=len(results),
            with_cv_id=sum(1 for r in results if r.mylar3_cv_id is not None),
        )

        return results

    def _parse_cv_id(self, comic_id: str | None) -> int | None:
        """Parse 'CV-47050' to 47050. Returns None if malformed."""
        if not comic_id:
            return None
        if comic_id.startswith(self.MYLAR3_CV_PREFIX):
            try:
                return int(comic_id[len(self.MYLAR3_CV_PREFIX) :])
            except ValueError:
                return None
        # Try parsing as plain integer
        try:
            return int(comic_id)
        except ValueError:
            return None

    def _parse_year(self, year_str: str | None) -> int | None:
        """Parse year string, handling NULL, '0000', and 4-digit strings."""
        if not year_str:
            return None
        try:
            year = int(year_str)
            if year == 0:
                return None
            return year
        except ValueError:
            return None

    def _resolve_location(self, location: str | None) -> str | None:
        """Apply path map translation to a ComicLocation string."""
        if not location:
            return None
        resolved = location
        for container_prefix, host_prefix in self._path_map.items():
            if resolved.startswith(container_prefix):
                resolved = host_prefix + resolved[len(container_prefix) :]
                break
        return resolved

    def _build_files(self, comic_paths: list[Path]) -> list[DiscoveredFile]:
        """Build DiscoveredFile objects from a list of comic file paths."""
        results: list[DiscoveredFile] = []
        for fpath in comic_paths:
            file_name = fpath.name
            file_format = fpath.suffix.lstrip(".").lower()
            try:
                file_size = fpath.stat().st_size
            except OSError:
                file_size = 0

            parsed = parse_filename(file_name)
            parsed_series: str | None = None
            parsed_issue_number: float | None = None
            parsed_year: int | None = None
            issue_number_raw: str | None = None
            if parsed:
                parsed_series = parsed.series
                parsed_issue_number = parsed.issue_number
                parsed_year = parsed.year
                if parsed.issue_number == int(parsed.issue_number):
                    issue_number_raw = str(int(parsed.issue_number))
                else:
                    issue_number_raw = str(parsed.issue_number)

            results.append(
                DiscoveredFile(
                    file_path=str(fpath),
                    file_name=file_name,
                    file_size=file_size,
                    file_format=file_format,
                    parsed_series=parsed_series,
                    parsed_issue_number=parsed_issue_number,
                    parsed_year=parsed_year,
                    parsed_publisher=None,
                    has_comicinfo=False,
                    comicvine_issue_id=None,
                    issue_number_raw=issue_number_raw,
                )
            )
        return results

    def _get_file_count(self, location: str | None) -> int:
        """Count comic files in a directory if it exists. Returns 0 otherwise."""
        resolved = self._resolve_location(location)
        if not resolved:
            return 0
        p = Path(resolved)
        if not p.exists() or not p.is_dir():
            return 0
        return sum(1 for f in p.iterdir() if f.suffix.lower() in COMIC_EXTENSIONS)
