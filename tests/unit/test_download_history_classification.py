"""Tests for shared download/post-processing history clauses."""

from __future__ import annotations

from pullbox.services.download_history_classification import cancelled_download_clause


def test_cancelled_download_clause_matches_failed_user_cancel() -> None:
    clause = cancelled_download_clause()
    compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))

    assert "download_history.state = 'FAILED'" in compiled
    assert "download_history.error_message = 'Cancelled by user'" in compiled
