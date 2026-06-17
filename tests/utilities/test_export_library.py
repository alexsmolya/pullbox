"""Tests for UT-5.1 — export library executor.

Verifies CSV and JSON export with BOM, field selection, multi-value
handling, unicode, edge cases (empty records, special characters).

Run:
    pytest tests/utilities/test_export_library.py -v
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors import export_library
from pullbox.utilities.executors.export_library import (
    ExportLibraryExecutor,
    export_records_csv,
    export_records_json,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Test Data ──────────────────────────────────────────────────

SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "series_name": "Batman",
        "issue_number": 1,
        "title": "The Court of Owls",
        "publisher": "DC Comics",
        "year": 2016,
        "file_path": "/comics/Batman/Batman #001.cbz",
        "status": "owned",
        "genres": "Superhero|Action",
    },
    {
        "series_name": "Saga",
        "issue_number": 1,
        "title": "Chapter One",
        "publisher": "Image Comics",
        "year": 2012,
        "file_path": "/comics/Saga/Saga #001.cbz",
        "status": "owned",
        "genres": "Sci-Fi|Fantasy",
    },
    {
        "series_name": "\u9032\u6483\u306e\u5de8\u4eba",
        "issue_number": 1,
        "title": None,
        "publisher": "Kodansha",
        "year": 2009,
        "file_path": None,
        "status": "wanted",
        "genres": "Action|Drama",
    },
]


# ── CSV Export ─────────────────────────────────────────────────


class TestCsvExport:
    """Verify CSV export format."""

    def test_csv_has_bom(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name"], output)
        raw = output.read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf"

    def test_csv_has_headers(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name", "issue_number"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        assert headers == ["series_name", "issue_number"]

    def test_csv_correct_row_count(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name"], output)
        content = output.read_text(encoding="utf-8-sig")
        lines = content.strip().split("\n")
        assert len(lines) == 4  # header + 3 records

    def test_csv_field_subset(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name", "year"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        assert headers == ["series_name", "year"]
        row = next(reader)
        assert row == ["Batman", "2016"]

    def test_csv_null_as_empty_string(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name", "title"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)  # skip header
        next(reader)  # Batman
        next(reader)  # Saga
        row = next(reader)  # 進撃の巨人 — title is None
        assert row[1] == ""

    def test_csv_unicode(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name"], output)
        content = output.read_text(encoding="utf-8-sig")
        assert "\u9032\u6483\u306e\u5de8\u4eba" in content

    def test_csv_commas_in_values(self, tmp_path: Path) -> None:
        records = [{"name": "Spider-Man, Amazing", "year": 2018}]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "year"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)
        row = next(reader)
        assert row[0] == "Spider-Man, Amazing"

    def test_csv_quotes_in_values(self, tmp_path: Path) -> None:
        records = [{"name": 'He said "hello"', "year": 2020}]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "year"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)
        row = next(reader)
        assert row[0] == 'He said "hello"'

    def test_csv_empty_records(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv([], ["series_name", "year"], output)
        content = output.read_text(encoding="utf-8-sig")
        lines = content.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_csv_single_field(self, tmp_path: Path) -> None:
        output = tmp_path / "export.csv"
        export_records_csv(SAMPLE_RECORDS, ["series_name"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        headers = next(reader)
        assert headers == ["series_name"]

    def test_csv_newlines_in_values(self, tmp_path: Path) -> None:
        """Field value containing newlines is properly quoted in CSV."""
        records: list[dict[str, Any]] = [
            {"name": "Batman", "summary": "Line one.\nLine two.\nLine three."},
        ]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "summary"], output)

        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)  # skip header
        row = next(reader)
        assert row[0] == "Batman"
        assert row[1] == "Line one.\nLine two.\nLine three."

    def test_csv_very_long_value(self, tmp_path: Path) -> None:
        """10KB summary not truncated in CSV output."""
        long_value = "x" * 10240
        records: list[dict[str, Any]] = [
            {"name": "Test", "summary": long_value},
        ]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "summary"], output)

        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)
        row = next(reader)
        assert len(row[1]) == 10240


# ── JSON Export ────────────────────────────────────────────────


class TestJsonExport:
    """Verify JSON export format."""

    def test_json_valid(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json(SAMPLE_RECORDS, ["series_name", "year"], output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 3

    def test_json_field_subset(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json(SAMPLE_RECORDS, ["series_name", "year"], output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert set(data[0].keys()) == {"series_name", "year"}

    def test_json_null_values(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json(SAMPLE_RECORDS, ["series_name", "title"], output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data[2]["title"] is None

    def test_json_pretty_printed(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json(SAMPLE_RECORDS, ["series_name"], output, pretty=True)
        content = output.read_text(encoding="utf-8")
        assert "\n  " in content  # indentation present

    def test_json_unicode(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json(SAMPLE_RECORDS, ["series_name"], output)
        content = output.read_text(encoding="utf-8")
        assert "\u9032\u6483\u306e\u5de8\u4eba" in content

    def test_json_empty_records(self, tmp_path: Path) -> None:
        output = tmp_path / "export.json"
        export_records_json([], ["series_name"], output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data == []

    def test_json_multi_value_as_array(self, tmp_path: Path) -> None:
        """Pipe-separated values in multi-value fields become arrays."""
        output = tmp_path / "export.json"
        export_records_json(
            SAMPLE_RECORDS,
            ["series_name", "genres"],
            output,
            multi_value_fields={"genres"},
        )
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data[0]["genres"] == ["Superhero", "Action"]

    def test_json_very_long_value(self, tmp_path: Path) -> None:
        """10KB summary value preserved in JSON output."""
        long_value = "y" * 10240
        records: list[dict[str, Any]] = [
            {"name": "Long", "summary": long_value},
        ]
        output = tmp_path / "export.json"
        export_records_json(records, ["name", "summary"], output)

        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data[0]["summary"]) == 10240


# ── Config Validation ──────────────────────────────────────────


class TestValidateConfig:
    """Verify config validation."""

    def test_valid_config(self) -> None:
        executor = ExportLibraryExecutor()
        errors = executor.validate_config(
            {
                "format": "csv",
                "fields": ["series_name", "issue_number"],
            }
        )
        assert errors == []

    def test_missing_format(self) -> None:
        executor = ExportLibraryExecutor()
        errors = executor.validate_config({"fields": ["series_name"]})
        assert any("format" in e.lower() for e in errors)

    def test_invalid_format(self) -> None:
        executor = ExportLibraryExecutor()
        errors = executor.validate_config({"format": "xml", "fields": ["x"]})
        assert any("format" in e.lower() for e in errors)

    def test_missing_fields(self) -> None:
        executor = ExportLibraryExecutor()
        errors = executor.validate_config({"format": "csv"})
        assert any("field" in e.lower() for e in errors)

    def test_empty_fields(self) -> None:
        executor = ExportLibraryExecutor()
        errors = executor.validate_config({"format": "csv", "fields": []})
        assert any("field" in e.lower() for e in errors)


# ── Process Item ───────────────────────────────────────────────


class TestProcessItem:
    """Verify export execution."""

    def test_csv_export_creates_file(self, tmp_path: Path) -> None:
        executor = ExportLibraryExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-001",
                "operation": "export",
                "records": SAMPLE_RECORDS,
            },
            job_config={
                "format": "csv",
                "fields": ["series_name", "year"],
                "export_folder": str(tmp_path),
            },
        )

        assert result.result == ItemResult.COMPLETED
        output_path = result.after_state.get("path", "")
        assert Path(output_path).exists()
        assert output_path.endswith(".csv")

    def test_json_export_creates_file(self, tmp_path: Path) -> None:
        executor = ExportLibraryExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-002",
                "operation": "export",
                "records": SAMPLE_RECORDS,
            },
            job_config={
                "format": "json",
                "fields": ["series_name", "year"],
                "export_folder": str(tmp_path),
            },
        )

        assert result.result == ItemResult.COMPLETED
        output_path = result.after_state.get("path", "")
        assert Path(output_path).exists()
        data = json.loads(Path(output_path).read_text())
        assert len(data) == 3

    def test_export_folder_placeholder_resolves_to_data_dir(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        executor = ExportLibraryExecutor()
        data_dir = tmp_path / "data-root"
        monkeypatch.setattr(
            "pullbox.config.get_settings",
            lambda: SimpleNamespace(library_root=tmp_path / "library-root", data_dir=data_dir),
        )
        result = executor.process_item(
            item_data={
                "id": "item-003",
                "operation": "export",
                "records": SAMPLE_RECORDS,
            },
            job_config={
                "format": "json",
                "fields": ["series_name", "year"],
                "export_folder": "{data}/exports",
            },
        )

        assert result.result == ItemResult.COMPLETED
        output_path = Path(result.after_state.get("path", ""))
        assert output_path.exists()
        assert output_path.parent == data_dir / "exports"

    def test_process_item_uses_job_context_records(self, tmp_path: Path) -> None:
        executor = ExportLibraryExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-004",
                "operation": "export",
                "records": [{"series_name": "ignored"}],
            },
            job_config={
                "format": "json",
                "fields": ["series_name"],
                "export_folder": str(tmp_path),
            },
            job_context={"records": [{"series_name": "from context"}]},
        )

        output_path = Path(result.after_state.get("path", ""))
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert result.result == ItemResult.COMPLETED
        assert data == [{"series_name": "from context"}]

    def test_process_item_reports_export_failures(self, monkeypatch) -> None:
        executor = ExportLibraryExecutor()
        monkeypatch.setattr(
            export_library,
            "resolve_export_directory",
            lambda _folder: (_ for _ in ()).throw(OSError("exports unavailable")),
        )

        result = executor.process_item(
            item_data={"id": "item-fail", "operation": "export", "records": SAMPLE_RECORDS},
            job_config={"format": "csv", "fields": ["series_name"]},
        )

        assert result.item_id == "item-fail"
        assert result.result == ItemResult.FAILED
        assert result.error_message == "exports unavailable"
        assert result.log_entries[0][0] == "ERROR"


class TestRollbackItem:
    """Verify export rollback behavior."""

    def test_rollback_deletes_export_file_from_dict_after_state(self, tmp_path: Path) -> None:
        output_path = tmp_path / "export.csv"
        output_path.write_text("data", encoding="utf-8")
        executor = ExportLibraryExecutor()

        result = executor.rollback_item(
            item_data={"id": "rollback-001", "after_state": {"path": str(output_path)}},
            job_config={},
        )

        assert result.result == ItemResult.COMPLETED
        assert not output_path.exists()
        assert "Deleted export file" in result.log_entries[0][1]

    def test_rollback_accepts_json_encoded_after_state(self, tmp_path: Path) -> None:
        output_path = tmp_path / "export.json"
        output_path.write_text("[]", encoding="utf-8")
        executor = ExportLibraryExecutor()

        result = executor.rollback_item(
            item_data={"id": "rollback-002", "after_state": json.dumps({"path": str(output_path)})},
            job_config={},
        )

        assert result.result == ItemResult.COMPLETED
        assert not output_path.exists()

    def test_rollback_reports_invalid_after_state_json(self) -> None:
        executor = ExportLibraryExecutor()

        result = executor.rollback_item(
            item_data={"id": "rollback-fail", "after_state": "not-json"},
            job_config={},
        )

        assert result.result == ItemResult.FAILED
        assert result.error_message is not None
        assert result.error_message.startswith("Rollback failed:")


@pytest.mark.asyncio
async def test_generate_items_returns_single_export_item() -> None:
    items = await ExportLibraryExecutor().generate_items({"format": "csv"})

    assert items == [{"operation": "export", "file_path": None}]


@pytest.mark.asyncio
async def test_build_job_context_fetches_export_records(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    root = LibraryRoot(name="Library", path=str(tmp_path), enabled=True)
    publisher = Publisher(name="DC Comics", comicvine_id=10)
    db_session.add_all([root, publisher])
    await db_session.flush()
    series = Series(
        title="Batman",
        sort_title="batman",
        year_start=2016,
        year_end=2026,
        status=SeriesStatus.CONTINUING,
        description="Dark Knight",
        comicvine_id=1234,
        comicvine_url="https://comicvine.test/batman",
        monitored=True,
        path=str(tmp_path / "Batman"),
        series_type=SeriesType.STANDARD,
        publisher_id=publisher.id,
        library_root_id=root.id,
    )
    db_session.add(series)
    await db_session.flush()
    issue = Issue(
        series_id=series.id,
        issue_number=1.0,
        title="I Am Gotham",
        issue_type=IssueType.ISSUE,
        status=IssueStatus.OWNED,
        release_date=date(2016, 6, 15),
        store_date=date(2016, 6, 14),
        page_count=32,
        comicvine_id=5678,
        comicvine_url="https://comicvine.test/batman-1",
    )
    db_session.add(issue)
    await db_session.flush()
    library_file = LibraryFile(
        issue_id=issue.id,
        library_root_id=root.id,
        file_path=str(tmp_path / "Batman" / "Batman 001.cbz"),
        file_name="Batman 001.cbz",
        file_size=123456,
        file_format=FileFormat.CBZ,
        file_hash="abc123",
        file_modified_at=datetime.now(tz=UTC),
        match_confidence=MatchConfidence.HIGH,
    )
    db_session.add(library_file)
    await db_session.flush()

    fields = [
        "series_title",
        "series_sort_title",
        "series_year_start",
        "series_year_end",
        "series_status",
        "series_type",
        "series_description",
        "series_comicvine_id",
        "series_comicvine_url",
        "series_monitored",
        "series_path",
        "issue_number",
        "issue_title",
        "issue_type",
        "issue_status",
        "release_date",
        "store_date",
        "page_count",
        "issue_comicvine_id",
        "issue_comicvine_url",
        "file_path",
        "file_name",
        "file_size",
        "file_format",
        "file_hash",
        "publisher",
        "publisher_comicvine_id",
    ]

    context = await ExportLibraryExecutor().build_job_context(
        db_session,
        {"fields": fields},
    )

    assert context["records"] == [
        {
            "series_title": "Batman",
            "series_sort_title": "batman",
            "series_year_start": 2016,
            "series_year_end": 2026,
            "series_status": "continuing",
            "series_type": "standard",
            "series_description": "Dark Knight",
            "series_comicvine_id": 1234,
            "series_comicvine_url": "https://comicvine.test/batman",
            "series_monitored": True,
            "series_path": str(tmp_path / "Batman"),
            "issue_number": 1.0,
            "issue_title": "I Am Gotham",
            "issue_type": "issue",
            "issue_status": "owned",
            "release_date": "2016-06-15",
            "store_date": "2016-06-14",
            "page_count": 32,
            "issue_comicvine_id": 5678,
            "issue_comicvine_url": "https://comicvine.test/batman-1",
            "file_path": str(tmp_path / "Batman" / "Batman 001.cbz"),
            "file_name": "Batman 001.cbz",
            "file_size": 123456,
            "file_format": "cbz",
            "file_hash": "abc123",
            "publisher": "DC Comics",
            "publisher_comicvine_id": 10,
        }
    ]


@pytest.mark.asyncio
async def test_fetch_export_records_handles_empty_library(db_session: AsyncSession) -> None:
    assert await ExportLibraryExecutor._fetch_export_records(db_session, ["series_title"]) == []


@pytest.mark.asyncio
async def test_fetch_export_records_returns_series_only_rows(
    db_session: AsyncSession,
) -> None:
    db_session.add(Series(title="No Issues", sort_title="no issues"))
    await db_session.flush()

    records = await ExportLibraryExecutor._fetch_export_records(
        db_session,
        ["series_title", "publisher"],
    )

    assert records == [{"series_title": "No Issues"}]


# ── Additional Export Edge Cases ───────────────────────────────


class TestExportAdditionalEdgeCases:
    """Additional edge cases from sprint guide gap analysis."""

    def test_csv_newlines_in_values(self, tmp_path: Path) -> None:
        """Field value containing newlines is properly quoted in CSV."""
        records: list[dict[str, Any]] = [
            {"name": "Batman", "summary": "Line one\nLine two\nLine three"},
        ]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "summary"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)  # skip header
        row = next(reader)
        assert "Line one\nLine two" in row[1]

    def test_csv_very_long_value_not_truncated(self, tmp_path: Path) -> None:
        """10KB+ field value is written in full."""
        long_value = "x" * 12000
        records: list[dict[str, Any]] = [{"name": "Test", "summary": long_value}]
        output = tmp_path / "export.csv"
        export_records_csv(records, ["name", "summary"], output)
        content = output.read_text(encoding="utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        next(reader)
        row = next(reader)
        assert len(row[1]) == 12000

    def test_json_very_long_value_preserved(self, tmp_path: Path) -> None:
        """Long value preserved in JSON export."""
        long_value = "y" * 15000
        records: list[dict[str, Any]] = [{"name": "Test", "summary": long_value}]
        output = tmp_path / "export.json"
        export_records_json(records, ["name", "summary"], output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data[0]["summary"]) == 15000
