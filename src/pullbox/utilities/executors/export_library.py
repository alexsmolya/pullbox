"""Export library executor — CSV and JSON export with field selection.

Exports library metadata to CSV (UTF-8 with BOM, comma-delimited) or
JSON (with optional pretty-printing). Supports field subset selection,
multi-value field splitting, and scope filtering.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from pullbox.models.issue import Issue
from pullbox.models.library import LibraryFile
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series
from pullbox.utilities.base_executor import ExecutionMode, ItemResult, JobExecutor, ProcessedItem
from pullbox.utilities.settings import resolve_export_directory

logger = structlog.get_logger(__name__)

_VALID_FORMATS = frozenset({"csv", "json"})


# ── Standalone Export Functions ────────────────────────────────


def export_records_csv(
    records: list[dict[str, Any]],
    fields: list[str],
    output_path: Path,
) -> None:
    """Export records to CSV with UTF-8 BOM header.

    Args:
        records: List of record dicts to export.
        fields: Ordered list of field names to include as columns.
        output_path: Path to write the CSV file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(fields)

        for record in records:
            row = []
            for field in fields:
                value = record.get(field)
                if value is None:
                    row.append("")
                else:
                    row.append(str(value))
            writer.writerow(row)


def export_records_json(
    records: list[dict[str, Any]],
    fields: list[str],
    output_path: Path,
    pretty: bool = False,
    multi_value_fields: set[str] | None = None,
) -> None:
    """Export records to JSON.

    Args:
        records: List of record dicts to export.
        fields: List of field names to include.
        output_path: Path to write the JSON file.
        pretty: If True, indent with 2 spaces.
        multi_value_fields: Set of field names whose pipe-separated
            values should be split into arrays.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mv_fields = multi_value_fields or set()

    exported: list[dict[str, Any]] = []
    for record in records:
        entry: dict[str, Any] = {}
        for field in fields:
            value = record.get(field)
            if field in mv_fields and isinstance(value, str) and "|" in value:
                entry[field] = [v.strip() for v in value.split("|")]
            else:
                entry[field] = value
        exported.append(entry)

    indent = 2 if pretty else None
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(exported, f, ensure_ascii=False, indent=indent)


# ── Executor ───────────────────────────────────────────────────


class ExportLibraryExecutor(JobExecutor):
    """Executor for library data export to CSV or JSON."""

    execution_mode = ExecutionMode.SERIAL

    def validate_config(self, job_config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        fmt = job_config.get("format")
        if not fmt:
            errors.append("format is required ('csv' or 'json')")
        elif fmt not in _VALID_FORMATS:
            errors.append(f"Invalid format: {fmt}. Supported: {', '.join(sorted(_VALID_FORMATS))}")
        fields = job_config.get("fields")
        if not fields:
            errors.append("fields is required (at least one field must be selected)")
        return errors

    async def build_job_context(
        self,
        session: Any,
        job_config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "records": await self._fetch_export_records(session, list(job_config.get("fields", [])))
        }

    async def generate_items(
        self,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a single export item."""
        return [
            {
                "operation": "export",
                "file_path": None,
            }
        ]

    def process_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Execute the export."""
        start = time.monotonic()
        item_id = item_data.get("id", "unknown")

        try:
            fmt = job_config.get("format", "csv")
            fields = job_config.get("fields", [])
            export_folder = job_config.get("export_folder")
            pretty = job_config.get("pretty", False)
            records = list((job_context or {}).get("records", item_data.get("records", [])))

            # Generate unique filename
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            export_dir = resolve_export_directory(export_folder)
            export_dir.mkdir(parents=True, exist_ok=True)

            if fmt == "csv":
                output_path = export_dir / f"pullbox_export_{timestamp}.csv"
                export_records_csv(records, fields, output_path)
            else:
                output_path = export_dir / f"pullbox_export_{timestamp}.json"
                multi_value_fields = set(job_config.get("multi_value_fields", []))
                export_records_json(
                    records,
                    fields,
                    output_path,
                    pretty=pretty,
                    multi_value_fields=multi_value_fields,
                )

            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.COMPLETED,
                after_state={
                    "path": str(output_path),
                    "format": fmt,
                    "record_count": len(records),
                    "field_count": len(fields),
                },
                duration_ms=duration_ms,
                log_entries=[
                    (
                        "INFO",
                        f"Exported {len(records)} records to {output_path.name}",
                        {"format": fmt, "fields": len(fields)},
                    ),
                ],
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.FAILED,
                duration_ms=duration_ms,
                error_message=str(exc),
                log_entries=[("ERROR", f"Export failed: {exc}", {})],
            )

    def rollback_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Rollback deletes the exported file."""
        start = time.monotonic()
        item_id = item_data.get("id", "unknown")

        try:
            after_state = item_data.get("after_state", {})
            if isinstance(after_state, str):
                import json as json_mod

                after_state = json_mod.loads(after_state)

            export_path = Path(after_state.get("path", ""))
            if export_path.exists():
                export_path.unlink()

            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.COMPLETED,
                duration_ms=duration_ms,
                log_entries=[("INFO", f"Deleted export file: {export_path.name}", {})],
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.FAILED,
                duration_ms=duration_ms,
                error_message=f"Rollback failed: {exc}",
                log_entries=[("ERROR", f"Rollback failed: {exc}", {})],
            )

    @staticmethod
    async def _fetch_export_records(
        session: Any,
        fields: list[str],
    ) -> list[dict[str, object]]:
        """Fetch export rows in a bounded number of queries."""
        needs_issue = any(
            f.startswith("issue_") or f in ("release_date", "store_date", "page_count")
            for f in fields
        )
        needs_file = any(f.startswith("file_") for f in fields)
        needs_publisher = any(f.startswith("publisher") for f in fields)

        series_rows = list((await session.execute(select(Series))).scalars().all())
        if not series_rows:
            return []

        publisher_by_id: dict[int, Publisher] = {}
        if needs_publisher:
            publisher_ids = sorted(
                {
                    int(series.publisher_id)
                    for series in series_rows
                    if series.publisher_id is not None
                }
            )
            if publisher_ids:
                publishers = list(
                    (
                        await session.execute(
                            select(Publisher).where(Publisher.id.in_(publisher_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                publisher_by_id = {publisher.id: publisher for publisher in publishers}

        issues_by_series: dict[int, list[Issue]] = {}
        if needs_issue:
            series_ids = [series.id for series in series_rows]
            issue_rows = list(
                (await session.execute(select(Issue).where(Issue.series_id.in_(series_ids))))
                .scalars()
                .all()
            )
            for issue in issue_rows:
                issues_by_series.setdefault(issue.series_id, []).append(issue)

        files_by_issue: dict[int, list[LibraryFile]] = {}
        if needs_file and needs_issue:
            issue_ids = [issue.id for issues in issues_by_series.values() for issue in issues]
            if issue_ids:
                file_rows = list(
                    (
                        await session.execute(
                            select(LibraryFile).where(LibraryFile.issue_id.in_(issue_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                for library_file in file_rows:
                    if library_file.issue_id is not None:
                        files_by_issue.setdefault(library_file.issue_id, []).append(library_file)

        records: list[dict[str, object]] = []
        for series in series_rows:
            issues = issues_by_series.get(series.id, [None]) if needs_issue else [None]
            publisher = (
                publisher_by_id.get(int(series.publisher_id))
                if needs_publisher and series.publisher_id is not None
                else None
            )

            for issue in issues:
                files: list[LibraryFile | None] = [None]
                if needs_file and issue is not None:
                    found_files = files_by_issue.get(issue.id, [])
                    if found_files:
                        files = found_files  # type: ignore[assignment]

                for library_file in files:
                    record: dict[str, object] = {}

                    if "series_title" in fields:
                        record["series_title"] = series.title
                    if "series_sort_title" in fields:
                        record["series_sort_title"] = series.sort_title
                    if "series_year_start" in fields:
                        record["series_year_start"] = series.year_start
                    if "series_year_end" in fields:
                        record["series_year_end"] = series.year_end
                    if "series_status" in fields:
                        record["series_status"] = (
                            str(series.status.value) if series.status else None
                        )
                    if "series_type" in fields:
                        record["series_type"] = (
                            str(series.series_type.value) if series.series_type else None
                        )
                    if "series_description" in fields:
                        record["series_description"] = series.description
                    if "series_comicvine_id" in fields:
                        record["series_comicvine_id"] = series.comicvine_id
                    if "series_comicvine_url" in fields:
                        record["series_comicvine_url"] = series.comicvine_url
                    if "series_monitored" in fields:
                        record["series_monitored"] = series.monitored
                    if "series_path" in fields:
                        record["series_path"] = series.path

                    if issue is not None:
                        if "issue_number" in fields:
                            record["issue_number"] = issue.issue_number
                        if "issue_title" in fields:
                            record["issue_title"] = issue.title
                        if "issue_type" in fields:
                            record["issue_type"] = (
                                str(issue.issue_type.value) if issue.issue_type else None
                            )
                        if "issue_status" in fields:
                            record["issue_status"] = (
                                str(issue.status.value) if issue.status else None
                            )
                        if "release_date" in fields:
                            record["release_date"] = (
                                str(issue.release_date) if issue.release_date else None
                            )
                        if "store_date" in fields:
                            record["store_date"] = (
                                str(issue.store_date) if issue.store_date else None
                            )
                        if "page_count" in fields:
                            record["page_count"] = issue.page_count
                        if "issue_comicvine_id" in fields:
                            record["issue_comicvine_id"] = issue.comicvine_id
                        if "issue_comicvine_url" in fields:
                            record["issue_comicvine_url"] = issue.comicvine_url

                    if library_file is not None:
                        if "file_path" in fields:
                            record["file_path"] = library_file.file_path
                        if "file_name" in fields:
                            record["file_name"] = library_file.file_name
                        if "file_size" in fields:
                            record["file_size"] = library_file.file_size
                        if "file_format" in fields:
                            record["file_format"] = (
                                str(library_file.file_format.value)
                                if library_file.file_format
                                else None
                            )
                        if "file_hash" in fields:
                            record["file_hash"] = library_file.file_hash

                    if publisher is not None:
                        if "publisher" in fields:
                            record["publisher"] = publisher.name
                        if "publisher_comicvine_id" in fields:
                            record["publisher_comicvine_id"] = publisher.comicvine_id

                    records.append(record)

        return records
