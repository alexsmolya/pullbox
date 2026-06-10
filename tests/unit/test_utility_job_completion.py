"""Tests for utility job dispatch completion decisions."""

from __future__ import annotations

from pullbox.utilities.base_executor import FinalizeResult, JobRunSummary
from pullbox.utilities.job_queue_completion import (
    build_completion_decision,
    merge_finalize_result,
)
from pullbox.utilities.models import JobState, JobType


def test_completion_decision_for_cancelling_job() -> None:
    decision = build_completion_decision(
        current=JobState.CANCELLING,
        job_type=JobType.FILE_CONVERT,
        summary=JobRunSummary(completed=2, failed=1, skipped=3),
    )

    assert decision.target_state == JobState.CANCELLED
    assert decision.log_level == "WARNING"
    assert decision.message == "Job cancelled. 2 completed, 1 failed, 3 skipped."
    assert decision.error_message is None


def test_completion_decision_for_all_failed_job() -> None:
    decision = build_completion_decision(
        current=JobState.RUNNING,
        job_type=JobType.FILE_CONVERT,
        summary=JobRunSummary(completed=0, failed=4, skipped=0),
    )

    assert decision.target_state == JobState.FAILED
    assert decision.log_level == "ERROR"
    assert decision.message == "Job failed. All 4 items failed."
    assert decision.error_message == "All 4 items failed"


def test_completion_decision_preserves_existing_zero_success_rollback_message() -> None:
    decision = build_completion_decision(
        current=JobState.RUNNING,
        job_type=JobType.ROLLBACK,
        summary=JobRunSummary(completed=0, failed=4, skipped=0),
    )

    assert decision.target_state == JobState.FAILED
    assert decision.message == "Job failed. All 4 items failed."


def test_completion_decision_for_partial_rollback_failure() -> None:
    decision = build_completion_decision(
        current=JobState.RUNNING,
        job_type=JobType.ROLLBACK,
        summary=JobRunSummary(completed=2, failed=1, skipped=0),
    )

    assert decision.target_state == JobState.FAILED
    assert decision.log_level == "ERROR"
    assert decision.message == "Rollback failed. 2 rolled back, 1 failed."
    assert decision.error_message == "Rollback failed. 2 items rolled back, 1 failed."


def test_completion_decision_for_success_with_failed_and_skipped_counts() -> None:
    decision = build_completion_decision(
        current=JobState.RUNNING,
        job_type=JobType.FILE_CONVERT,
        summary=JobRunSummary(completed=3, failed=1, skipped=2),
    )

    assert decision.target_state == JobState.COMPLETED
    assert decision.log_level == "INFO"
    assert decision.message == "Job completed. 3 succeeded, 1 failed, 2 skipped."
    assert decision.error_message is None


def test_merge_finalize_result_adds_final_parts_and_log_level() -> None:
    decision = build_completion_decision(
        current=JobState.RUNNING,
        job_type=JobType.FILE_CONVERT,
        summary=JobRunSummary(completed=3, failed=0, skipped=0),
    )

    merged = merge_finalize_result(
        decision,
        FinalizeResult(
            final_parts=["dry-run mode", "1 unsupported"],
            final_log_level="WARNING",
        ),
    )

    assert merged.message == "Job completed. 3 succeeded, dry-run mode, 1 unsupported."
    assert merged.log_level == "WARNING"
