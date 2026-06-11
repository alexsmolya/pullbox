"""Tests for cover storage directory resolution (C-8.3).

Verifies:
- Cover directory resolves to {comics_directory}/.covers/ when configured
- Cover directory falls back to settings.covers_dir when comics_directory missing
- Cover directory created automatically if missing
- Cover path includes series ID for organization
- Covers always written to .covers/{series_id}/ (never series folder)
- Series folder covers still served as fallback for serving
- Legacy location checked as fallback after .covers/
- _find_cover_file finds images by stem
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pullbox.api.v1.covers import _find_cover_file


class TestFindCoverFile:
    """Cover file finder checks multiple image extensions."""

    def test_finds_jpg(self, tmp_path: Path) -> None:
        (tmp_path / "cover.jpg").write_text("img")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.jpg"

    def test_finds_png(self, tmp_path: Path) -> None:
        (tmp_path / "cover.png").write_text("img")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.png"

    def test_finds_webp(self, tmp_path: Path) -> None:
        (tmp_path / "cover.webp").write_text("img")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.webp"

    def test_prefers_jpg_over_png(self, tmp_path: Path) -> None:
        (tmp_path / "cover.jpg").write_text("jpg")
        (tmp_path / "cover.png").write_text("png")
        assert _find_cover_file(tmp_path, "cover") == tmp_path / "cover.jpg"

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert _find_cover_file(tmp_path, "cover") is None

    def test_nonexistent_directory(self) -> None:
        assert _find_cover_file(Path("/nonexistent/dir"), "cover") is None

    def test_issue_number_stem(self, tmp_path: Path) -> None:
        (tmp_path / "issue_001.jpg").write_text("img")
        assert _find_cover_file(tmp_path, "issue_001") == tmp_path / "issue_001.jpg"

    def test_rejects_stem_path_traversal(self, tmp_path: Path) -> None:
        cover_dir = tmp_path / "covers"
        cover_dir.mkdir()
        outside = tmp_path / "outside.jpg"
        outside.write_text("img")

        assert _find_cover_file(cover_dir, "../outside") is None


class TestResolveCoversDir:
    """Cover directory resolution prefers {comics_dir}/.covers/ over legacy path."""

    @pytest.mark.asyncio
    async def test_uses_comics_dir_when_configured(self) -> None:
        from pullbox.services.cover_resolver import resolve_covers_dir

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "/data/comics"
        mock_session.execute.return_value = mock_result

        result = await resolve_covers_dir(mock_session)
        assert result == Path("/data/comics/.covers")

    @pytest.mark.asyncio
    async def test_falls_back_to_settings_when_no_comics_dir(self) -> None:
        from pullbox.services.cover_resolver import resolve_covers_dir

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("pullbox.services.cover_resolver.get_settings") as mock_settings:
            mock_settings.return_value.covers_dir = Path("/data/covers")
            result = await resolve_covers_dir(mock_session)
        assert result == Path("/data/covers")

    @pytest.mark.asyncio
    async def test_falls_back_when_comics_dir_empty_string(self) -> None:
        from pullbox.services.cover_resolver import resolve_covers_dir

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ""
        mock_session.execute.return_value = mock_result

        with patch("pullbox.services.cover_resolver.get_settings") as mock_settings:
            mock_settings.return_value.covers_dir = Path("/data/covers")
            result = await resolve_covers_dir(mock_session)
        assert result == Path("/data/covers")


class TestCoverServing:
    """Cover serving checks .covers/ before legacy location."""

    def test_series_folder_cover_resolved(self, tmp_path: Path) -> None:
        series_dir = tmp_path / "Batman (2016)"
        series_dir.mkdir()
        (series_dir / "cover.jpg").write_text("img")

        cover = _find_cover_file(series_dir, "cover")
        assert cover is not None
        assert cover == series_dir / "cover.jpg"

    def test_covers_subfolder_cover_resolved(self, tmp_path: Path) -> None:
        covers_dir = tmp_path / ".covers" / "42"
        covers_dir.mkdir(parents=True)
        (covers_dir / "series.jpg").write_text("img")

        cover = _find_cover_file(covers_dir, "series")
        assert cover is not None
        assert cover == covers_dir / "series.jpg"

    def test_issue_cover_in_covers_subfolder(self, tmp_path: Path) -> None:
        covers_dir = tmp_path / ".covers" / "42"
        covers_dir.mkdir(parents=True)
        (covers_dir / "issue_99.jpg").write_text("img")

        cover = _find_cover_file(covers_dir, "issue_99")
        assert cover is not None


class TestPurgeSeriesCoverCache:
    """Series cover cache cleanup removes active and legacy directories."""

    @pytest.mark.asyncio
    async def test_removes_resolved_and_legacy_cache_dirs(self, tmp_path: Path) -> None:
        from pullbox.services.cover_cache_service import purge_series_cover_cache

        active_base = tmp_path / "active"
        legacy_base = tmp_path / "legacy"
        for base in (active_base, legacy_base):
            cover_dir = base / "42"
            cover_dir.mkdir(parents=True)
            (cover_dir / "series.jpg").write_bytes(b"stale-image")

        mock_session = AsyncMock()
        settings = SimpleNamespace(covers_dir=legacy_base)
        with (
            patch(
                "pullbox.services.cover_cache_service.resolve_covers_dir",
                AsyncMock(return_value=active_base),
            ),
            patch("pullbox.services.cover_cache_service.get_settings", return_value=settings),
        ):
            await purge_series_cover_cache(mock_session, 42)

        assert not (active_base / "42").exists()
        assert not (legacy_base / "42").exists()


class TestCoverDownloadFallback:
    """Cover download always writes to .covers/{series_id}/."""

    @pytest.mark.asyncio
    async def test_download_to_covers_dir_when_no_series_path(self, tmp_path: Path) -> None:
        from pullbox.services.metadata_service import MetadataService

        mock_provider = MagicMock()
        mock_provider.get_cover_image = AsyncMock(return_value=b"fake-image")
        covers_dir = tmp_path / ".covers"
        service = MetadataService(mock_provider, covers_dir=covers_dir)

        series = MagicMock()
        series.id = 42
        series.path = None

        await service.download_series_cover(series, "https://example.com/cover.jpg")

        cover_path = covers_dir / "42" / "series.jpg"
        assert cover_path.exists()
        assert cover_path.read_bytes() == b"fake-image"
        assert series.cover_path == "/api/v1/series/42/cover"

    @pytest.mark.asyncio
    async def test_always_writes_to_covers_dir(self, tmp_path: Path) -> None:
        """Covers always go to .covers/{series_id}/, even when series has a path."""
        from pullbox.services.metadata_service import MetadataService

        mock_provider = MagicMock()
        mock_provider.get_cover_image = AsyncMock(return_value=b"fake-image")
        covers_dir = tmp_path / ".covers"
        service = MetadataService(mock_provider, covers_dir=covers_dir)

        series_dir = tmp_path / "Batman"
        series_dir.mkdir()

        series = MagicMock()
        series.id = 42
        series.path = str(series_dir)

        await service.download_series_cover(series, "https://example.com/cover.jpg")

        # Cover goes to .covers/42/series.jpg, NOT the series folder
        assert (covers_dir / "42" / "series.jpg").exists()
        assert not (series_dir / "cover.jpg").exists()
        assert series.cover_path == "/api/v1/series/42/cover"
