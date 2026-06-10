"""Shared state helpers for import-series ComicVine match fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pullbox.models.import_job import ImportedSeries


def clear_auto_cv_match_fields(imp_series: ImportedSeries) -> None:
    """Clear auto-derived ComicVine fields while preserving user overrides.

    Rows that were only auto-seeded from scan metadata or auto-matching should not
    continue to look identified once they fall back to a true no-match state. User
    selections are preserved so manual recovery context is not lost.
    """
    if imp_series.user_selected_cv_id is not None:
        return

    imp_series.cv_id = None
    imp_series.cv_title = None
    imp_series.cv_year = None
    imp_series.cv_publisher = None
    imp_series.cv_issue_count = None
    imp_series.cv_url = None
    imp_series.cv_match_score = None
    imp_series.cv_match_method = None
