"""Tests for import-series match-state helpers."""

from __future__ import annotations

from types import SimpleNamespace

from pullbox.services.import_series_match_state import clear_auto_cv_match_fields


def test_clear_auto_cv_match_fields_preserves_user_selected_match() -> None:
    imp_series = SimpleNamespace(
        user_selected_cv_id=1234,
        cv_id=1234,
        cv_title="User Selected",
        cv_year=2026,
    )

    clear_auto_cv_match_fields(imp_series)

    assert imp_series.cv_id == 1234
    assert imp_series.cv_title == "User Selected"
    assert imp_series.cv_year == 2026
