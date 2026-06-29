"""Tests for utility/import file-mutation guardrails."""

from __future__ import annotations

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.utilities.import_guards import (
    ensure_utility_job_allowed_during_import,
    utility_job_mutates_library,
)
from pullbox.utilities.models import JobType


def test_utility_job_mutation_detection_is_config_aware() -> None:
    assert utility_job_mutates_library(JobType.MASS_RENAME, {}) is True
    assert (
        utility_job_mutates_library(JobType.INTEGRITY_CHECK, {"corrupt_action": "report"}) is False
    )
    assert (
        utility_job_mutates_library(JobType.INTEGRITY_CHECK, {"corrupt_action": "quarantine"})
        is True
    )
    assert (
        utility_job_mutates_library(JobType.LIBRARY_PERMISSIONS, {"run_mode": "dry_run"}) is False
    )
    assert utility_job_mutates_library(JobType.LIBRARY_PERMISSIONS, {"run_mode": "apply"}) is True


@pytest.mark.asyncio
async def test_mutating_utility_job_is_blocked_during_import(db_session) -> None:
    db_session.add(
        ImportJob(
            source_path="/imports/test",
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.IMPORTING,
        )
    )
    await db_session.commit()

    with pytest.raises(ValidationError, match="currently writing files"):
        await ensure_utility_job_allowed_during_import(
            db_session,
            job_type=JobType.MASS_CONVERT_PIPELINE,
            config={},
        )


@pytest.mark.asyncio
async def test_mutating_utility_job_is_blocked_during_stalled_import(db_session) -> None:
    db_session.add(
        ImportJob(
            source_path="/imports/test",
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.STALLED,
        )
    )
    await db_session.commit()

    with pytest.raises(ValidationError, match="currently writing files"):
        await ensure_utility_job_allowed_during_import(
            db_session,
            job_type=JobType.MASS_RENAME,
            config={},
        )


@pytest.mark.asyncio
async def test_non_mutating_utility_job_is_allowed_during_import(db_session) -> None:
    db_session.add(
        ImportJob(
            source_path="/imports/test",
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.IMPORTING,
        )
    )
    await db_session.commit()

    await ensure_utility_job_allowed_during_import(
        db_session,
        job_type=JobType.INTEGRITY_CHECK,
        config={"corrupt_action": "report"},
    )
