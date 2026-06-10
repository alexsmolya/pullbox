"""Completion decision helpers for utility job dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.utilities.models import JobState, JobType

if TYPE_CHECKING:
    from pullbox.utilities.base_executor import FinalizeResult, JobRunSummary


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    """Terminal state and log outcome for a dispatched utility job."""

    target_state: JobState
    message: str
    log_level: str = "INFO"
    error_message: str | None = None


def build_completion_decision(
    *,
    current: JobState,
    job_type: str,
    summary: JobRunSummary,
) -> CompletionDecision:
    """Return the terminal state/message for a completed dispatch pass."""
    if current == JobState.CANCELLING:
        return CompletionDecision(
            target_state=JobState.CANCELLED,
            message=(
                f"Job cancelled. {summary.completed} completed, "
                f"{summary.failed} failed, {summary.skipped} skipped."
            ),
            log_level="WARNING",
        )
    if summary.failed > 0 and summary.completed == 0:
        return CompletionDecision(
            target_state=JobState.FAILED,
            message=f"Job failed. All {summary.failed} items failed.",
            log_level="ERROR",
            error_message=f"All {summary.failed} items failed",
        )
    if job_type == JobType.ROLLBACK and summary.failed > 0:
        return CompletionDecision(
            target_state=JobState.FAILED,
            message=f"Rollback failed. {summary.completed} rolled back, {summary.failed} failed.",
            log_level="ERROR",
            error_message=(
                f"Rollback failed. {summary.completed} items rolled back, {summary.failed} failed."
            ),
        )

    parts = [f"{summary.completed} succeeded"]
    if summary.failed > 0:
        parts.append(f"{summary.failed} failed")
    if summary.skipped > 0:
        parts.append(f"{summary.skipped} skipped")
    return CompletionDecision(
        target_state=JobState.COMPLETED,
        message=f"Job completed. {', '.join(parts)}.",
    )


def merge_finalize_result(
    decision: CompletionDecision,
    finalize_result: FinalizeResult,
) -> CompletionDecision:
    """Merge executor-specific final text/log-level into a completion decision."""
    message = decision.message
    if finalize_result.final_parts and message.startswith("Job completed. "):
        base_parts = message.removeprefix("Job completed. ").removesuffix(".")
        merged_parts = [base_parts, *finalize_result.final_parts]
        message = f"Job completed. {', '.join(part for part in merged_parts if part)}."

    return CompletionDecision(
        target_state=decision.target_state,
        message=message,
        log_level=finalize_result.final_log_level or decision.log_level,
        error_message=decision.error_message,
    )
