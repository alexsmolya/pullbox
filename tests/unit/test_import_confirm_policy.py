"""Tests for confirm-import policy helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.config import SystemConfig
from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.schemas.import_job import ConfirmImportRequest
from pullbox.services.import_confirm_policy import apply_confirm_import_policy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _make_job() -> ImportJob:
    return ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
        monitored=False,
    )


async def test_apply_confirm_policy_uses_global_search_on_add(
    db_session: AsyncSession,
) -> None:
    db_session.add(SystemConfig(key="search_on_add_default", value="true", value_type="bool"))
    await db_session.flush()
    job = _make_job()

    await apply_confirm_import_policy(
        db_session,
        job,
        ConfirmImportRequest(series_ids=[1], monitored=False, target_library_root_id=7),
    )

    assert job.search_on_add is True
    assert job.monitored is True
    assert job.target_library_root_id == 7
    assert job.move_to_library is True


async def test_apply_confirm_policy_rejects_conflicting_search_override(
    db_session: AsyncSession,
) -> None:
    db_session.add(SystemConfig(key="search_on_add_default", value="false", value_type="bool"))
    await db_session.flush()

    with pytest.raises(ValidationError, match="global import policy"):
        await apply_confirm_import_policy(
            db_session,
            _make_job(),
            ConfirmImportRequest(series_ids=[1], search_on_add=True),
        )


async def test_apply_confirm_policy_rejects_deprecated_move_override(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValidationError, match="no longer supported"):
        await apply_confirm_import_policy(
            db_session,
            _make_job(),
            ConfirmImportRequest(series_ids=[1], move_to_library=False),
        )


async def test_apply_confirm_policy_persists_ingest_defaults(
    db_session: AsyncSession,
) -> None:
    db_session.add(SystemConfig(key="post_processing_method", value="copy", value_type="string"))
    db_session.add(
        SystemConfig(
            key="convert_to_preferred_format_on_import",
            value="true",
            value_type="bool",
        )
    )
    db_session.add(
        SystemConfig(
            key="update_embedded_comicinfo_from_match_on_import",
            value="true",
            value_type="bool",
        )
    )
    await db_session.flush()
    job = _make_job()

    await apply_confirm_import_policy(
        db_session,
        job,
        ConfirmImportRequest(
            series_ids=[1],
            update_embedded_comicinfo_from_match=True,
        ),
    )

    assert job.transfer_method == "copy"
    assert job.convert_to_preferred_format is True
    assert job.update_embedded_comicinfo_from_match is True


async def test_apply_confirm_policy_rejects_convert_with_link_transfer(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        SystemConfig(key="post_processing_method", value="hardlink", value_type="string")
    )
    db_session.add(
        SystemConfig(
            key="convert_to_preferred_format_on_import",
            value="true",
            value_type="bool",
        )
    )
    await db_session.flush()

    with pytest.raises(ValidationError, match="Normalize Imported Archives"):
        await apply_confirm_import_policy(
            db_session,
            _make_job(),
            ConfirmImportRequest(series_ids=[1]),
        )


async def test_apply_confirm_policy_rejects_comicinfo_update_with_link_transfer(
    db_session: AsyncSession,
) -> None:
    db_session.add(SystemConfig(key="post_processing_method", value="symlink", value_type="string"))
    db_session.add(
        SystemConfig(
            key="update_embedded_comicinfo_from_match_on_import",
            value="true",
            value_type="bool",
        )
    )
    await db_session.flush()

    with pytest.raises(ValidationError, match=r"ComicInfo\.xml"):
        await apply_confirm_import_policy(
            db_session,
            _make_job(),
            ConfirmImportRequest(
                series_ids=[1],
                update_embedded_comicinfo_from_match=True,
            ),
        )
