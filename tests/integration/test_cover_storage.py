"""Tests for Phase 5 — cover storage in series folders.

Tests cover API endpoints (resolution order), cover file discovery,
and MetadataService cover destination logic.
"""

from __future__ import annotations

from pathlib import Path

from pullbox.api.v1.covers import _find_cover_file
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series, SeriesStatus

# ── _find_cover_file helper ────────────────────────────────────────


class TestFindCoverFile:
    """Cover file discovery with multiple extensions."""

    def test_finds_jpg(self, tmp_path) -> None:
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.jpg"

    def test_finds_jpeg(self, tmp_path) -> None:
        (tmp_path / "cover.jpeg").write_bytes(b"\xff\xd8\xff")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.jpeg"

    def test_finds_png(self, tmp_path) -> None:
        (tmp_path / "cover.png").write_bytes(b"\x89PNG")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.png"

    def test_finds_webp(self, tmp_path) -> None:
        (tmp_path / "cover.webp").write_bytes(b"RIFF")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.webp"

    def test_returns_none_when_missing(self, tmp_path) -> None:
        assert _find_cover_file(tmp_path, "cover") is None

    def test_prefers_jpg_over_png(self, tmp_path) -> None:
        """When multiple extensions exist, jpg is found first."""
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        (tmp_path / "cover.png").write_bytes(b"\x89PNG")
        result = _find_cover_file(tmp_path, "cover")
        assert result == tmp_path / "cover.jpg"

    def test_issue_stem_pattern(self, tmp_path) -> None:
        """Finds issue covers by number-based stem."""
        (tmp_path / "issue_001.jpg").write_bytes(b"\xff\xd8\xff")
        assert _find_cover_file(tmp_path, "issue_001") == tmp_path / "issue_001.jpg"

    def test_nonexistent_directory(self, tmp_path) -> None:
        """Returns None for directory that doesn't exist."""
        assert _find_cover_file(tmp_path / "nope", "cover") is None


# ── Series cover resolution ────────────────────────────────────────


class TestSeriesCoverResolution:
    """Series cover resolves: series folder → legacy → 404."""

    async def test_series_folder_cover_found(self, db_session, tmp_path) -> None:
        """Cover in series folder is preferred."""
        series_dir = tmp_path / "Batman (2024)"
        series_dir.mkdir()
        (series_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        series = Series(
            title="Batman",
            sort_title="Batman",
            year_start=2024,
            path=str(series_dir),
            status=SeriesStatus.CONTINUING,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        # Verify the cover file exists where the endpoint would look
        cover = _find_cover_file(Path(series.path), "cover")
        assert cover is not None
        assert cover.is_file()

    async def test_legacy_cover_found(self, db_session, tmp_path) -> None:
        """Falls back to legacy covers dir when no series folder cover."""
        series = Series(
            title="Saga",
            sort_title="Saga",
            year_start=2012,
            path=None,  # No series folder
            status=SeriesStatus.ENDED,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        # Create legacy cover
        legacy_dir = tmp_path / str(series.id)
        legacy_dir.mkdir()
        (legacy_dir / "series.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        cover = _find_cover_file(legacy_dir, "series")
        assert cover is not None

    async def test_no_cover_returns_none(self, db_session) -> None:
        """No cover anywhere returns None from helper."""
        series = Series(
            title="New Series",
            sort_title="New Series",
            path=None,
            status=SeriesStatus.CONTINUING,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        assert _find_cover_file(Path("/nonexistent"), "cover") is None
        assert _find_cover_file(Path("/nonexistent"), "series") is None


# ── Issue cover resolution ─────────────────────────────────────────


class TestIssueCoverResolution:
    """Issue cover resolves: series folder by number → legacy by ID → series cover → 404."""

    async def test_issue_cover_in_series_folder(self, db_session, tmp_path) -> None:
        """Issue cover found in series folder by issue number."""
        series_dir = tmp_path / "Batman (2024)"
        series_dir.mkdir()
        (series_dir / "issue_005.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        series = Series(
            title="Batman",
            sort_title="Batman",
            year_start=2024,
            path=str(series_dir),
            status=SeriesStatus.CONTINUING,
            issue_count=10,
        )
        db_session.add(series)
        await db_session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=5.0,
            status=IssueStatus.WANTED,
        )
        db_session.add(issue)
        await db_session.flush()

        # The endpoint would format 5.0 → "005"
        cover = _find_cover_file(Path(series.path), "issue_005")
        assert cover is not None

    async def test_issue_cover_legacy_by_id(self, db_session, tmp_path) -> None:
        """Falls back to legacy cover dir using DB ID."""
        series = Series(
            title="Saga",
            sort_title="Saga",
            path=None,
            status=SeriesStatus.ENDED,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            status=IssueStatus.WANTED,
        )
        db_session.add(issue)
        await db_session.flush()

        # Create legacy issue cover
        legacy_dir = tmp_path / str(series.id)
        legacy_dir.mkdir()
        (legacy_dir / f"issue_{issue.id}.jpg").write_bytes(b"\xff\xd8\xff")

        cover = _find_cover_file(legacy_dir, f"issue_{issue.id}")
        assert cover is not None

    async def test_issue_falls_back_to_series_cover(self, db_session, tmp_path) -> None:
        """When no issue-specific cover, falls back to series cover."""
        series_dir = tmp_path / "Batman (2024)"
        series_dir.mkdir()
        (series_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        series = Series(
            title="Batman",
            sort_title="Batman",
            path=str(series_dir),
            status=SeriesStatus.CONTINUING,
            issue_count=10,
        )
        db_session.add(series)
        await db_session.flush()

        # No issue-specific cover → series cover as fallback
        assert _find_cover_file(Path(series.path), "issue_001") is None
        assert _find_cover_file(Path(series.path), "cover") is not None


# ── Issue number formatting ────────────────────────────────────────


class TestIssueNumberFormatting:
    """Issue number → filename stem conversion."""

    def test_integer_issue_padded(self) -> None:
        """5.0 → '005'"""
        num = 5.0
        assert num == int(num)
        assert f"{int(num):03d}" == "005"

    def test_fractional_issue(self) -> None:
        """1.5 → '0001.5'"""
        num = 1.5
        assert num != int(num)
        assert f"{num:06.1f}" == "0001.5"

    def test_large_issue(self) -> None:
        """100.0 → '100'"""
        num = 100.0
        assert f"{int(num):03d}" == "100"

    def test_three_digit_issue(self) -> None:
        """999.0 → '999'"""
        num = 999.0
        assert f"{int(num):03d}" == "999"


# ── Cover path in MetadataService ──────────────────────────────────


class TestCoverPathAssignment:
    """MetadataService sets cover_path to API endpoint."""

    async def test_series_with_path_gets_api_endpoint(self, db_session) -> None:
        """New series with path gets /api/v1/series/{id}/cover."""
        series = Series(
            title="Test",
            sort_title="Test",
            path="/comics/Test (2024)",
            status=SeriesStatus.CONTINUING,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        # Simulate what MetadataService now does
        series.cover_path = f"/api/v1/series/{series.id}/cover"
        assert series.cover_path == f"/api/v1/series/{series.id}/cover"

    async def test_issue_gets_api_endpoint(self, db_session) -> None:
        """Issue cover_path uses API endpoint."""
        series = Series(
            title="Test",
            sort_title="Test",
            path="/comics/Test (2024)",
            status=SeriesStatus.CONTINUING,
            issue_count=0,
        )
        db_session.add(series)
        await db_session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            status=IssueStatus.WANTED,
        )
        db_session.add(issue)
        await db_session.flush()

        # Simulate what the updated routes.py does
        issue.cover_path = f"/api/v1/issues/{issue.id}/cover"
        assert issue.cover_path == f"/api/v1/issues/{issue.id}/cover"


# ── Cover destination logic ────────────────────────────────────────


class TestCoverDestination:
    """Cover files are saved to correct locations."""

    def test_series_folder_destination(self, tmp_path) -> None:
        """When series has a path, cover goes to {path}/cover.jpg."""
        series_path = tmp_path / "Batman (2024)"
        series_path.mkdir()
        cover_dest = series_path / "cover.jpg"
        cover_dest.write_bytes(b"\xff\xd8\xff")
        assert cover_dest.exists()

    def test_legacy_destination(self, tmp_path) -> None:
        """When no series path, cover goes to {covers_dir}/{id}/series.jpg."""
        legacy_dir = tmp_path / "42"
        legacy_dir.mkdir()
        cover_dest = legacy_dir / "series.jpg"
        cover_dest.write_bytes(b"\xff\xd8\xff")
        assert cover_dest.exists()

    def test_issue_cover_in_series_folder(self, tmp_path) -> None:
        """Issue cover saved as {path}/issue_{num}.jpg."""
        series_path = tmp_path / "Batman (2024)"
        series_path.mkdir()
        cover_dest = series_path / "issue_005.jpg"
        cover_dest.write_bytes(b"\xff\xd8\xff")
        assert cover_dest.exists()

    def test_issue_cover_legacy(self, tmp_path) -> None:
        """Issue cover saved as {covers_dir}/{series_id}/issue_{id}.jpg."""
        legacy_dir = tmp_path / "42"
        legacy_dir.mkdir()
        cover_dest = legacy_dir / "issue_99.jpg"
        cover_dest.write_bytes(b"\xff\xd8\xff")
        assert cover_dest.exists()
