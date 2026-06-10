"""Focused API coverage for utility trash management."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from pullbox.models.config import SystemConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService
from pullbox.utilities.job_queue import JobQueueManager
from pullbox.utilities.router import set_queue_manager

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-utilities-trash")


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.fixture(autouse=True)
def _setup_queue_manager() -> None:
    set_queue_manager(JobQueueManager(session_factory=None))


@pytest.fixture
async def utility_trash_dir(
    sec_db: async_sessionmaker,
    tmp_path: Path,
) -> Path:
    trash_dir = tmp_path / ".trash"
    trash_dir.mkdir(parents=True)

    async with sec_db() as session:
        session.add(
            SystemConfig(
                key="utility_trash_folder",
                value=str(trash_dir),
                value_type="string",
            )
        )
        session.add(
            SystemConfig(
                key="utility_trash_retention_days",
                value="30",
                value_type="int",
            )
        )
        await session.commit()

    return trash_dir


@pytest.mark.asyncio
async def test_empty_trash_endpoint_deletes_contents_and_preserves_root(
    authenticated_client,
    utility_trash_dir: Path,
) -> None:  # type: ignore[no-untyped-def]
    nested_dir = utility_trash_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "one.cbz").write_text("one")
    (utility_trash_dir / "two.cb7").write_text("two")

    response = await authenticated_client.post(
        "/api/v1/utilities/trash/empty",
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Trash emptied."
    assert data["deleted_entries"] == 3
    assert utility_trash_dir.exists()
    assert list(utility_trash_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_create_job_enforces_trash_retention_cleanup(
    authenticated_client,
    utility_trash_dir: Path,
) -> None:  # type: ignore[no-untyped-def]
    old_file = utility_trash_dir / "old.cbz"
    new_file = utility_trash_dir / "new.cbz"
    old_file.write_text("old")
    new_file.write_text("new")

    old_timestamp = (datetime.now(tz=UTC) - timedelta(days=45)).timestamp()
    os.utime(old_file, (old_timestamp, old_timestamp))

    response = await authenticated_client.post(
        "/api/v1/utilities/jobs",
        json={
            "job_type": "file_convert",
            "display_name": "Retention test job",
            "config": {
                "target_format": "cbz",
            },
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 201
    assert not old_file.exists()
    assert new_file.exists()
