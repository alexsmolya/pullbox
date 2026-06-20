"""Unit tests for Mylar3 database reader."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from pullbox.core.exceptions import MylarReadError
from pullbox.core.mylar3_reader import Mylar3Reader

if TYPE_CHECKING:
    from pathlib import Path


def _create_mylar_db(
    db_path: Path,
    series: list[dict[str, str | int | None]] | None = None,
    issues: list[dict[str, str | int | None]] | None = None,
    annuals: list[dict[str, str | int | None]] | None = None,
) -> None:
    """Create a fake Mylar3 database with a comic table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE comics (
            ComicID TEXT,
            ComicName TEXT,
            ComicYear TEXT,
            ComicPublisher TEXT,
            ComicLocation TEXT,
            Status TEXT,
            Total INTEGER,
            ComicImage TEXT
        )
    """)
    for s in series or []:
        conn.execute(
            "INSERT INTO comics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.get("ComicID"),
                s.get("ComicName"),
                s.get("ComicYear"),
                s.get("ComicPublisher"),
                s.get("ComicLocation"),
                s.get("Status", "Active"),
                s.get("Total", 0),
                s.get("ComicImage"),
            ),
        )
    if issues is not None:
        conn.execute("""
            CREATE TABLE issues (
                IssueID TEXT,
                ComicName TEXT,
                IssueName TEXT,
                Issue_Number TEXT,
                ComicID TEXT,
                Location TEXT,
                IssueDate TEXT,
                Int_IssueNumber INTEGER
            )
        """)
        for issue in issues:
            conn.execute(
                "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    issue.get("IssueID"),
                    issue.get("ComicName"),
                    issue.get("IssueName"),
                    issue.get("Issue_Number"),
                    issue.get("ComicID"),
                    issue.get("Location"),
                    issue.get("IssueDate"),
                    issue.get("Int_IssueNumber"),
                ),
            )
    if annuals is not None:
        conn.execute("""
            CREATE TABLE annuals (
                IssueID TEXT,
                Issue_Number TEXT,
                IssueName TEXT,
                IssueDate TEXT,
                ComicID TEXT,
                Location TEXT,
                Int_IssueNumber INTEGER,
                ComicName TEXT,
                ReleaseComicID TEXT,
                ReleaseComicName TEXT
            )
        """)
        for annual in annuals:
            conn.execute(
                "INSERT INTO annuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    annual.get("IssueID"),
                    annual.get("Issue_Number"),
                    annual.get("IssueName"),
                    annual.get("IssueDate"),
                    annual.get("ComicID"),
                    annual.get("Location"),
                    annual.get("Int_IssueNumber"),
                    annual.get("ComicName"),
                    annual.get("ReleaseComicID"),
                    annual.get("ReleaseComicName"),
                ),
            )
    conn.commit()
    conn.close()


class TestBasicRead:
    """Test 1: Basic read — 3 series, all fields populated."""

    @pytest.mark.asyncio
    async def test_reads_all_series(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {
                    "ComicID": "CV-47050",
                    "ComicName": "Batman",
                    "ComicYear": "2016",
                    "ComicPublisher": "DC Comics",
                    "ComicLocation": str(tmp_path / "comics" / "Batman"),
                    "Status": "Active",
                    "Total": 85,
                },
                {
                    "ComicID": "CV-49030",
                    "ComicName": "Saga",
                    "ComicYear": "2012",
                    "ComicPublisher": "Image Comics",
                    "ComicLocation": str(tmp_path / "comics" / "Saga"),
                    "Status": "Active",
                    "Total": 54,
                },
                {
                    "ComicID": "CV-40796",
                    "ComicName": "Invincible",
                    "ComicYear": "2003",
                    "ComicPublisher": "Image Comics",
                    "ComicLocation": str(tmp_path / "comics" / "Invincible"),
                    "Status": "Ended",
                    "Total": 144,
                },
            ],
        )
        # Create comic dirs with files
        for name in ["Batman", "Saga", "Invincible"]:
            d = tmp_path / "comics" / name
            d.mkdir(parents=True)
            (d / "issue001.cbz").touch()

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 3
        by_name = {r.raw_series_name: r for r in results}
        assert by_name["Batman"].mylar3_cv_id == 47050
        assert by_name["Batman"].raw_year == 2016
        assert by_name["Batman"].raw_publisher == "DC Comics"
        assert by_name["Saga"].mylar3_cv_id == 49030
        assert by_name["Invincible"].mylar3_cv_id == 40796


class TestNullYear:
    """Test 2: NULL year handled gracefully."""

    @pytest.mark.asyncio
    async def test_null_year(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-100", "ComicName": "NoYear", "ComicYear": None},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].raw_year is None

    @pytest.mark.asyncio
    async def test_zero_year(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-100", "ComicName": "ZeroYear", "ComicYear": "0000"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].raw_year is None


class TestComicVineId:
    """Test 3: ComicVine ID preserved from Mylar3 ComicID field."""

    @pytest.mark.asyncio
    async def test_cv_id_extraction(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-47050", "ComicName": "Batman"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert results[0].mylar3_cv_id == 47050

    @pytest.mark.asyncio
    async def test_issue_metadata_is_preserved_from_mylar3_issues(
        self,
        tmp_path: Path,
    ) -> None:
        db = tmp_path / "mylar.db"
        series_dir = tmp_path / "comics" / "Batman"
        series_dir.mkdir(parents=True)
        issue_path = series_dir / "Batman 001 (2016).cbz"
        issue_path.touch()
        _create_mylar_db(
            db,
            [
                {
                    "ComicID": "CV-47050",
                    "ComicName": "Batman",
                    "ComicYear": "2016",
                    "ComicPublisher": "DC Comics",
                    "ComicLocation": str(series_dir),
                    "Status": "Ended",
                    "Total": 85,
                },
            ],
            issues=[
                {
                    "IssueID": "500001",
                    "ComicID": "47050",
                    "ComicName": "Batman",
                    "IssueName": "I Am Gotham",
                    "Issue_Number": "1",
                    "Location": issue_path.name,
                    "IssueDate": "2016-08-01",
                },
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        series = results[0]
        assert series.diagnostics["issue_count_hint"] == 85
        assert series.diagnostics["series_status"] == "Ended"
        assert series.files[0].comicvine_issue_id == 500001
        assert series.files[0].comicvine_series_id == 47050
        assert series.files[0].issue_count_hint == 85
        assert series.files[0].series_status == "Ended"
        assert series.files[0].metadata_signals["comicvine_issue_id"] == "mylar3"
        assert series.files[0].metadata_signals["comicvine_series_id"] == "mylar3"
        assert series.files[0].metadata_diagnostics["mylar3_issue"] == {
            "issue_id": 500001,
            "issue_number": "1",
            "title": "I Am Gotham",
            "release_date": "2016-08-01",
        }


class TestStatusHandling:
    """Test 4: Import ALL series regardless of Mylar3 status."""

    @pytest.mark.asyncio
    async def test_all_statuses_imported(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        statuses = ["Active", "Ended", "Paused", "Wanted"]
        series = [
            {"ComicID": f"CV-{i}", "ComicName": f"Series{i}", "Status": s}
            for i, s in enumerate(statuses)
        ]
        _create_mylar_db(db, series)

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 4

    @pytest.mark.asyncio
    async def test_wanted_has_no_files(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {
                    "ComicID": "CV-1",
                    "ComicName": "Wanted",
                    "Status": "Wanted",
                    "ComicLocation": None,
                },
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert results[0].has_files is False


class TestMissingFiles:
    """Test 5: Series with no comic files on disk."""

    @pytest.mark.asyncio
    async def test_nonexistent_location(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {
                    "ComicID": "CV-1",
                    "ComicName": "Gone",
                    "ComicLocation": str(tmp_path / "nonexistent"),
                },
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].file_count == 0
        assert results[0].has_files is False


class TestInvalidDatabase:
    """Test 6: Invalid database file."""

    @pytest.mark.asyncio
    async def test_not_sqlite(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "mylar.db"
        bad_file.write_text("not a database")

        reader = Mylar3Reader(bad_file)
        with pytest.raises(MylarReadError, match="read"):
            await reader.read_series()


class TestWrongDatabase:
    """Test 7: Valid SQLite but no comics table."""

    @pytest.mark.asyncio
    async def test_no_comic_table(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other_table (id INTEGER)")
        conn.close()

        reader = Mylar3Reader(db)
        with pytest.raises(MylarReadError, match="Not a Mylar3 database"):
            await reader.read_series()


class TestLargeDatabase:
    """Test 8: Large database performance."""

    @pytest.mark.asyncio
    async def test_500_series(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        series = [
            {"ComicID": f"CV-{i}", "ComicName": f"Series {i}", "ComicYear": "2020"}
            for i in range(500)
        ]
        _create_mylar_db(db, series)

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 500


class TestMissingPath:
    """Test 9: Path does not exist."""

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path: Path) -> None:
        reader = Mylar3Reader(tmp_path / "nonexistent.db")
        with pytest.raises(FileNotFoundError):
            await reader.read_series()


class TestDuplicateCvId:
    """Test 10: Duplicate comicvine_id deduplicated."""

    @pytest.mark.asyncio
    async def test_dedup_by_cv_id(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-47050", "ComicName": "Batman"},
                {"ComicID": "CV-47050", "ComicName": "Batman (Duplicate)"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].raw_series_name == "Batman"


class TestPathMapTranslation:
    """Test 11: Path map translates container paths to host paths."""

    @pytest.mark.asyncio
    async def test_path_map(self, tmp_path: Path) -> None:
        storage = tmp_path / "storage" / "comics" / "Batman (2016)"
        storage.mkdir(parents=True)
        for i in range(3):
            (storage / f"issue{i:03d}.cbz").touch()

        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {
                    "ComicID": "CV-1",
                    "ComicName": "Batman",
                    "ComicYear": "2016",
                    "ComicLocation": "/data/comics/Batman (2016)",
                },
            ],
        )

        reader = Mylar3Reader(db, path_map={"/data": str(tmp_path / "storage")})
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].file_count == 3


class TestPathMapNoMatch:
    """Test 12: Path map doesn't match — file count 0, handled gracefully."""

    @pytest.mark.asyncio
    async def test_unmatched_path_map(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-1", "ComicName": "Batman", "ComicLocation": "/other/path/Batman"},
            ],
        )

        reader = Mylar3Reader(db, path_map={"/data": str(tmp_path / "storage")})
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].file_count == 0
        assert results[0].has_files is False


class TestMalformedCvId:
    """Edge cases for ComicVine ID parsing."""

    @pytest.mark.asyncio
    async def test_malformed_cv_prefix(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-abc", "ComicName": "Broken"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].mylar3_cv_id is None

    @pytest.mark.asyncio
    async def test_non_cv_non_integer_id(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "xyz", "ComicName": "Weird"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].mylar3_cv_id is None

    @pytest.mark.asyncio
    async def test_plain_integer_id(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "47050", "ComicName": "PlainId"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].mylar3_cv_id == 47050


class TestMalformedYear:
    """Edge case: non-numeric year string."""

    @pytest.mark.asyncio
    async def test_non_numeric_year(self, tmp_path: Path) -> None:
        db = tmp_path / "mylar.db"
        _create_mylar_db(
            db,
            [
                {"ComicID": "CV-1", "ComicName": "BadYear", "ComicYear": "abcd"},
            ],
        )

        reader = Mylar3Reader(db)
        results = await reader.read_series()

        assert len(results) == 1
        assert results[0].raw_year is None
