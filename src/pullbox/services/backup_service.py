"""Backup service — create, list, delete, and restore Pullbox backups.

Produces zip archives containing the SQLite database and a metadata file.
Uses SQLite's built-in backup API for safe hot copies of the database
while the application is running.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import structlog

import pullbox
from pullbox.core.exceptions import BackupError
from pullbox.core.timezone import get_timezone

logger = structlog.get_logger(__name__)

BACKUP_PREFIX = "pullbox_backup_"
BACKUP_EXTENSION = ".zip"
DB_FILENAME = "pullbox.db"
METADATA_FILENAME = "backup_info.json"
PRE_RESTORE_PREFIX = "pullbox_pre_restore_"
PRE_RESTORE_EXTENSION = ".db"
_BACKUP_BUSY_TIMEOUT_PRAGMA = "PRAGMA busy_timeout=30000"


@dataclass
class BackupInfo:
    """Metadata about a backup archive."""

    filename: str
    created_at: str
    size_bytes: int
    pullbox_version: str
    db_size_bytes: int
    backup_type: str  # "manual" or "scheduled"


class BackupService:
    """Manages backup creation, listing, deletion, and restoration."""

    _BACKUP_ATTEMPTS = 5
    _BACKUP_BUSY_TIMEOUT_MS = 30_000
    _BACKUP_RETRY_BASE_DELAY_SECONDS = 0.5
    _BACKUP_RETRY_PAGE_COUNT = 2048

    def __init__(self, backup_dir: Path, db_path: Path) -> None:
        self._backup_dir = backup_dir
        self._db_path = db_path

    _MIN_BACKUP_SIZE = 512  # Minimum valid backup ZIP size in bytes

    def create_backup(self, backup_type: str = "manual") -> BackupInfo:
        """Create a new backup archive.

        Uses SQLite's online backup API to safely copy the database while
        the application may be actively writing to it.

        Args:
            backup_type: Either "manual" (user-triggered) or "scheduled".

        Returns:
            BackupInfo with details about the created archive.

        Raises:
            BackupError: If the backup cannot be created or fails verification.
        """
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError(f"Cannot create backup directory: {exc}") from exc

        timestamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S")
        filename = f"{BACKUP_PREFIX}{timestamp}{BACKUP_EXTENSION}"
        zip_path = self._backup_dir / filename

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                tmp_db = tmp_path / DB_FILENAME

                # Verify source database exists before attempting backup
                if not self._db_path.is_file():
                    raise BackupError(f"Database file not found: {self._db_path}")

                # Safe hot copy using SQLite backup API
                self._backup_database(tmp_db)

                db_size = tmp_db.stat().st_size

                # Write metadata file
                metadata = {
                    "pullbox_version": pullbox.__version__,
                    "created_at": datetime.now(UTC).isoformat(),
                    "backup_type": backup_type,
                    "db_size_bytes": db_size,
                    "contents": [DB_FILENAME],
                    "notes": (
                        "Restore this backup by placing the zip in your backup directory "
                        "and using the Pullbox UI or API restore endpoint. "
                        "IMPORTANT: Keep the same resolved application secret after restore. "
                        "For normal Docker installs, preserve /data/config.xml. For "
                        "env-managed deployments, keep PULLBOX_SECRET_KEY unchanged. "
                        "Changing the secret prevents encrypted credentials from decrypting "
                        "and invalidates existing browser sessions."
                    ),
                }
                metadata_path = tmp_path / METADATA_FILENAME
                metadata_path.write_text(json.dumps(metadata, indent=2))

                # Create zip archive
                with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
                    zf.write(tmp_db, DB_FILENAME)
                    zf.write(metadata_path, METADATA_FILENAME)

            # Verify the created backup
            self._verify_backup(zip_path)

        except BackupError:
            # Clean up partial ZIP on failure
            zip_path.unlink(missing_ok=True)
            raise
        except (sqlite3.Error, OSError) as exc:
            zip_path.unlink(missing_ok=True)
            logger.error("backup_creation_failed", error=str(exc), exc_info=True)
            raise BackupError(f"Backup creation failed: {exc}") from exc

        zip_size = zip_path.stat().st_size

        logger.info(
            "backup_created",
            filename=filename,
            size_bytes=zip_size,
            db_size_bytes=db_size,
            backup_type=backup_type,
        )

        return BackupInfo(
            filename=filename,
            created_at=str(metadata["created_at"]),
            size_bytes=zip_size,
            pullbox_version=pullbox.__version__,
            db_size_bytes=db_size,
            backup_type=backup_type,
        )

    def list_backups(self) -> list[BackupInfo]:
        """List all backup archives in the backup directory.

        Returns backups sorted by creation time, newest first.
        """
        if not self._backup_dir.is_dir():
            return []

        backups: list[BackupInfo] = []
        for path in sorted(
            self._backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_EXTENSION}"), reverse=True
        ):
            try:
                info = self._read_backup_info(path)
                if info:
                    backups.append(info)
            except Exception:
                logger.warning("backup_metadata_read_failed", filename=path.name)
                # Include it anyway with minimal info
                backups.append(
                    BackupInfo(
                        filename=path.name,
                        created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                        size_bytes=path.stat().st_size,
                        pullbox_version="unknown",
                        db_size_bytes=0,
                        backup_type="unknown",
                    )
                )

        return backups

    def delete_backup(self, filename: str) -> bool:
        """Delete a specific backup archive.

        Args:
            filename: Name of the backup zip file.

        Returns:
            True if deleted, False if not found.
        """
        path = self._backup_dir / filename
        if not self._is_valid_backup_path(path):
            return False

        path.unlink()
        logger.info("backup_deleted", filename=filename)
        return True

    def get_backup_path(self, filename: str) -> Path | None:
        """Return the full path to a backup file, or None if invalid/missing."""
        path = self._backup_dir / filename
        if self._is_valid_backup_path(path):
            return path
        return None

    def restore_backup(self, filename: str) -> bool:
        """Restore the database from a backup archive.

        Extracts the database from the zip and replaces the current one.
        The application should be restarted after this operation.

        Args:
            filename: Name of the backup zip file.

        Returns:
            True if restored successfully, False if backup not found.
        """
        path = self._backup_dir / filename
        if not self._is_valid_backup_path(path):
            return False

        self._verify_backup(path)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Extract the database from the zip
            with ZipFile(path, "r") as zf:
                zf.extract(DB_FILENAME, tmp_path)

            extracted_db = tmp_path / DB_FILENAME
            self._verify_restore_database(extracted_db)

            # Create a backup of the current database before overwriting
            if self._db_path.exists():
                timestamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S")
                safety_backup = (
                    self._backup_dir / f"{PRE_RESTORE_PREFIX}{timestamp}{PRE_RESTORE_EXTENSION}"
                )
                self._backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self._db_path, safety_backup)
                logger.info("pre_restore_backup_created", path=str(safety_backup))

            # Replace the database
            shutil.copy2(extracted_db, self._db_path)

            # Also remove WAL and SHM files so SQLite starts clean
            for suffix in (".db-wal", ".db-shm"):
                wal_path = self._db_path.with_suffix(suffix)
                if wal_path.exists():
                    wal_path.unlink()

        logger.info("backup_restored", filename=filename)
        return True

    def cleanup_old_backups(self, retention_days: int) -> int:
        """Delete scheduled backups older than the retention period.

        Manual backups are never automatically deleted.

        Args:
            retention_days: Maximum age in days for scheduled backups.

        Returns:
            Number of backups deleted.
        """
        if not self._backup_dir.is_dir():
            return 0

        cutoff = datetime.now(UTC).timestamp() - (retention_days * 86400)
        deleted = 0

        for path in self._backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_EXTENSION}"):
            try:
                info = self._read_backup_info(path)
                # Only auto-delete scheduled backups
                if info and info.backup_type != "scheduled":
                    continue
                if info is None:
                    # Metadata missing — skip to be safe
                    continue
            except Exception:
                # Corrupted metadata — skip rather than risk deleting a manual backup
                logger.warning("backup_cleanup_skipped_corrupt", filename=path.name)
                continue

            if self._backup_created_timestamp(path, info) < cutoff:
                path.unlink()
                deleted += 1
                logger.info("backup_retention_cleanup", filename=path.name)

        if deleted:
            logger.info("backup_cleanup_complete", deleted=deleted, retention_days=retention_days)

        return deleted

    # ── Private helpers ────────────────────────────────────────────

    def _verify_backup(self, zip_path: Path) -> None:
        """Verify a backup ZIP is valid and contains expected files."""
        if zip_path.stat().st_size < self._MIN_BACKUP_SIZE:
            raise BackupError(f"Backup too small ({zip_path.stat().st_size} bytes), likely corrupt")
        with ZipFile(zip_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                raise BackupError(f"Backup ZIP corrupt: bad file {bad_file}")
            names = zf.namelist()
            if DB_FILENAME not in names:
                raise BackupError("Backup ZIP missing database file")
            if METADATA_FILENAME not in names:
                raise BackupError("Backup ZIP missing metadata file")

    def _backup_database(self, dest: Path) -> None:
        """Use SQLite's backup API for a safe online copy."""
        last_error: sqlite3.Error | None = None

        for attempt in range(1, self._BACKUP_ATTEMPTS + 1):
            source_conn: sqlite3.Connection | None = None
            dest_conn: sqlite3.Connection | None = None
            try:
                source_uri = f"{self._db_path.resolve().as_uri()}?mode=ro"
                source_conn = sqlite3.connect(
                    source_uri,
                    uri=True,
                    timeout=self._BACKUP_BUSY_TIMEOUT_MS / 1000,
                )
                dest_conn = sqlite3.connect(
                    str(dest),
                    timeout=self._BACKUP_BUSY_TIMEOUT_MS / 1000,
                )
                source_conn.execute(_BACKUP_BUSY_TIMEOUT_PRAGMA)
                dest_conn.execute(_BACKUP_BUSY_TIMEOUT_PRAGMA)
                source_conn.backup(
                    dest_conn,
                    pages=self._BACKUP_RETRY_PAGE_COUNT,
                    sleep=0.05,
                )
                return
            except sqlite3.Error as exc:
                last_error = exc
                if dest.exists():
                    dest.unlink(missing_ok=True)
                if not self._is_transient_backup_error(exc) or attempt >= self._BACKUP_ATTEMPTS:
                    raise
                delay = self._BACKUP_RETRY_BASE_DELAY_SECONDS * attempt
                logger.warning(
                    "backup_database_retrying",
                    attempt=attempt,
                    max_attempts=self._BACKUP_ATTEMPTS,
                    delay_seconds=delay,
                    error=str(exc),
                )
                time.sleep(delay)
            finally:
                if dest_conn is not None:
                    dest_conn.close()
                if source_conn is not None:
                    source_conn.close()

        if last_error is not None:
            raise last_error

    @staticmethod
    def _is_transient_backup_error(exc: sqlite3.Error) -> bool:
        """Return True when a backup failure looks retryable."""
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "disk i/o error",
                "database is locked",
                "database table is locked",
                "locking protocol",
                "database busy",
            )
        )

    def _read_backup_info(self, path: Path) -> BackupInfo | None:
        """Read metadata from a backup zip archive."""
        if not path.is_file():
            return None

        try:
            with ZipFile(path, "r") as zf:
                if METADATA_FILENAME not in zf.namelist():
                    return None
                raw = zf.read(METADATA_FILENAME)
                meta = json.loads(raw)
        except Exception:
            return None

        return BackupInfo(
            filename=path.name,
            created_at=meta.get("created_at", ""),
            size_bytes=path.stat().st_size,
            pullbox_version=meta.get("pullbox_version", "unknown"),
            db_size_bytes=meta.get("db_size_bytes", 0),
            backup_type=meta.get("backup_type", "unknown"),
        )

    def _verify_restore_database(self, db_path: Path) -> None:
        """Verify the extracted database can be opened and passes quick_check."""
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(db_path))
            result = conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as exc:
            raise BackupError(f"Backup database failed validation: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

        if not result or str(result[0]).lower() != "ok":
            raise BackupError("Backup database failed validation: quick_check did not return ok")

    @staticmethod
    def _backup_created_timestamp(path: Path, info: BackupInfo | None) -> float:
        """Return the best-known creation timestamp for a backup archive."""
        if info is not None and info.created_at:
            try:
                created_at = datetime.fromisoformat(info.created_at)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                return created_at.timestamp()
            except (TypeError, ValueError):
                pass
        return path.stat().st_mtime

    def _is_valid_backup_path(self, path: Path) -> bool:
        """Verify a path is a valid backup file inside the backup directory."""
        try:
            # Resolve to prevent path traversal
            resolved = path.resolve()
            backup_dir_resolved = self._backup_dir.resolve()
            return (
                resolved.parent == backup_dir_resolved
                and resolved.name.startswith(BACKUP_PREFIX)
                and resolved.name.endswith(BACKUP_EXTENSION)
                and resolved.is_file()
            )
        except (OSError, ValueError):
            return False
