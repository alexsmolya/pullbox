"""Tests for Alembic migration chain — verify migrations apply cleanly.

Runs the full migration chain against a fresh SQLite database file
and verifies that Phase 2 columns and config keys exist.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from alembic import command
from alembic.config import Config

# Path to the alembic directory (relative to this test file)
_ALEMBIC_DIR = Path(__file__).resolve().parent.parent.parent / "alembic"


@pytest.fixture
def alembic_cfg(tmp_path):
    """Create an Alembic config pointing at a temp SQLite database.

    Uses the async driver for Alembic (which uses async_engine_from_config)
    and the sync driver for inspection queries.
    """
    db_path = tmp_path / "test.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    cfg = Config(str(_ALEMBIC_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", async_url)

    # Set the env var that env.py reads
    os.environ["PULLBOX_DB_URL"] = async_url
    yield cfg, sync_url
    os.environ.pop("PULLBOX_DB_URL", None)


def _get_columns(sync_url: str, table: str) -> set[str]:
    """Get column names for a table using a sync engine."""
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        return {col["name"] for col in inspector.get_columns(table)}
    finally:
        engine.dispose()


class TestMigrationChain:
    """Verify the full Alembic migration chain applies cleanly."""

    def test_upgrade_to_head(self, alembic_cfg) -> None:
        """All migrations apply without error."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            tables = inspect(engine).get_table_names()
            assert "series" in tables
            assert "issues" in tables
            assert "library_roots" in tables
            assert "system_config" in tables
        finally:
            engine.dispose()

    def test_series_has_path_column(self, alembic_cfg) -> None:
        """Phase 2 migration adds path column to series."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "series")
        assert "path" in columns
        assert "library_root_id" in columns

    def test_series_has_issue_catalog_checked_timestamp(self, alembic_cfg) -> None:
        """Issue catalog scheduling tracks checks separately from full syncs."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "series")
        assert "issue_catalog_last_checked_at" in columns

    def test_issues_has_issue_type_column(self, alembic_cfg) -> None:
        """Phase 2 migration adds issue_type column to issues."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "issues")
        assert "issue_type" in columns

    def test_issue_type_default_value(self, alembic_cfg) -> None:
        """issue_type column defaults to 'issue'."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO series (title, sort_title, status, issue_count, "
                        "monitored) "
                        "VALUES ('Test', 'Test', 'continuing', 0, 0)"
                    )
                )
                series_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

                conn.execute(
                    text(
                        "INSERT INTO issues (series_id, issue_number, status) "
                        "VALUES (:sid, 1.0, 'wanted')"
                    ),
                    {"sid": series_id},
                )

                result = conn.execute(
                    text("SELECT issue_type FROM issues WHERE series_id = :sid"), {"sid": series_id}
                ).scalar()
                assert result == "issue"
                conn.commit()
        finally:
            engine.dispose()

    def test_naming_config_keys_seeded(self, alembic_cfg) -> None:
        """Phase 2 migration seeds the naming configuration keys."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        expected_keys = {
            "series_folder_template",
            "comic_file_template",
            "annual_file_template",
            "non_standard_file_template",
            "rename_on_import",
            "replace_illegal_characters",
            "colon_replacement",
            "create_empty_series_folders",
            "delete_empty_folders",
        }

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT key FROM system_config"))
                keys = {row[0] for row in result.fetchall()}
        finally:
            engine.dispose()

        assert expected_keys.issubset(keys), f"Missing keys: {expected_keys - keys}"

    def test_series_library_root_fk(self, alembic_cfg) -> None:
        """library_root_id FK on series references library_roots."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            fks = inspect(engine).get_foreign_keys("series")
            root_fk = [fk for fk in fks if "library_root_id" in fk["constrained_columns"]]
            assert len(root_fk) == 1
            assert root_fk[0]["referred_table"] == "library_roots"
        finally:
            engine.dispose()

    def test_downgrade_then_upgrade(self, alembic_cfg) -> None:
        """Migration can be downgraded and re-applied."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "series")
        assert "path" in columns
        assert "library_root_id" in columns

    def test_import_jobs_has_materialization_audit_fields(self, alembic_cfg) -> None:
        """Import jobs record the effective materialization policy for auditability."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "import_jobs")

        assert "torrent_import_strategy" in columns
        assert "effective_import_strategy" in columns
        assert "effective_transfer_method" in columns
        assert "source_preserved" in columns
        assert "ingest_policy_snapshot" in columns

    def test_library_files_has_naming_snapshot(self, alembic_cfg) -> None:
        """Library files keep the naming inputs used at placement time."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "library_files")

        assert "naming_snapshot" in columns

    def test_naming_snapshot_migration_backfills_series_path(self, alembic_cfg) -> None:
        """Existing library files materialize missing series folder paths."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "g9h0i1j2k345")

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO library_roots "
                        "(name, path, enabled, created_at, updated_at) "
                        "VALUES ('Comics', '/library', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                root_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                conn.execute(
                    text(
                        "INSERT INTO series "
                        "(comicvine_id, title, sort_title, year_start, status, issue_count, "
                        "monitored, series_type, alternate_names, created_at, updated_at) "
                        "VALUES (123, 'Batman', 'Batman', 2024, 'CONTINUING', 1, 0, "
                        "'STANDARD', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                series_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                conn.execute(
                    text(
                        "INSERT INTO issues "
                        "(series_id, issue_number, status, issue_type, manual_skip, "
                        "created_at, updated_at) "
                        "VALUES (:series_id, 1.0, 'OWNED', 'ISSUE', 0, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"series_id": series_id},
                )
                issue_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                conn.execute(
                    text(
                        "INSERT INTO library_files "
                        "(file_path, file_name, file_size, file_format, file_modified_at, "
                        "match_confidence, issue_id, library_root_id, has_comicinfo, "
                        "created_at, updated_at) "
                        "VALUES ('/library/Batman (2024)/Batman (2024) #001.cbz', "
                        "'Batman (2024) #001.cbz', 100, 'CBZ', CURRENT_TIMESTAMP, "
                        "'HIGH', :issue_id, :root_id, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"issue_id": issue_id, "root_id": root_id},
                )
                conn.commit()
        finally:
            engine.dispose()

        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT path, library_root_id FROM series WHERE title = 'Batman'")
                ).one()
        finally:
            engine.dispose()

        assert row[0] == "/library/Batman (2024)"
        assert row[1] == root_id

    def test_whats_new_release_cache_table(self, alembic_cfg) -> None:
        """What's New release payloads are cached in a dedicated table."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        columns = _get_columns(sync_url, "whats_new_release_cache")

        assert {
            "id",
            "cache_key",
            "cache_kind",
            "store_date",
            "publisher",
            "payload",
            "fetched_at",
            "last_successful_refresh_at",
            "created_at",
            "updated_at",
        }.issubset(columns)

        engine = create_engine(sync_url)
        try:
            inspector = inspect(engine)
            indexes = {index["name"] for index in inspector.get_indexes("whats_new_release_cache")}
            unique_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("whats_new_release_cache")
            }
        finally:
            engine.dispose()

        assert "uq_whats_new_release_cache_key" in unique_constraints
        assert "ix_whats_new_release_cache_kind" in indexes
        assert "ix_whats_new_release_cache_fetched_at" in indexes
        assert "ix_whats_new_release_cache_last_success" in indexes

    def test_usage_stats_instance_id_config_seeded(self, alembic_cfg) -> None:
        """Telemetry instance ID config exists but starts empty."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT value, value_type FROM system_config "
                        "WHERE key = 'usage_stats_instance_id'"
                    )
                ).one()
        finally:
            engine.dispose()

        assert row[0] == ""
        assert row[1] == "string"

    def test_upgrade_backfills_year_end_for_ended_series(self, alembic_cfg) -> None:
        """Ended series with a missing year_end are repaired on upgrade."""
        cfg, sync_url = alembic_cfg
        command.upgrade(cfg, "u6p7q8r9s012")

        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO series "
                        "(id, title, sort_title, year_start, year_end, status, issue_count, "
                        "monitored, series_type) "
                        "VALUES "
                        "(1, 'Thanos: The Infinity Revelation', 'Thanos: The Infinity Revelation', "
                        "2014, NULL, 'ENDED', 1, 0, 'HARDCOVER'), "
                        "(2, 'Fallback Hardcover', 'Fallback Hardcover', "
                        "2020, NULL, 'ENDED', 0, 0, 'HARDCOVER')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO issues "
                        "(series_id, issue_number, release_date, status, issue_type) "
                        "VALUES (1, 1.0, '2014-08-27', 'OWNED', 'GN')"
                    )
                )

            command.upgrade(cfg, "head")

            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id, year_end FROM series WHERE id IN (1, 2) ORDER BY id")
                ).fetchall()
        finally:
            engine.dispose()

        assert rows[0][1] == 2014
        assert rows[1][1] == 2020
