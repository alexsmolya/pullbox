from __future__ import annotations

from pullbox.core.duration_format import replace_duration_ms_tokens
from pullbox.ui.routes import (
    _health_check_response_label,
    _health_parenthetical_next_line,
    _health_response_label,
)


class TestHealthResponseLabel:
    def test_formats_sub_second_values_in_ms(self) -> None:
        assert _health_response_label(250) == "250ms"

    def test_formats_sub_millisecond_values(self) -> None:
        assert _health_response_label(0.4) == "<1ms"

    def test_formats_second_scale_values(self) -> None:
        assert _health_response_label(1234) == "1.2s"

    def test_formats_minute_scale_values(self) -> None:
        assert _health_response_label(65000) == "65.0s"


class TestHealthCheckResponseLabel:
    def test_extracts_response_time_from_simple_message(self) -> None:
        assert _health_check_response_label("Connected (1234ms)") == "1.2s"

    def test_extracts_primary_response_time_when_message_contains_threshold(self) -> None:
        assert _health_check_response_label("SELECT 1 took 1200ms (threshold: 500ms)") == "1.2s"

    def test_returns_message_when_no_response_time_present(self) -> None:
        assert _health_check_response_label("No recent status message recorded.") == (
            "No recent status message recorded."
        )


class TestReplaceDurationMsTokens:
    def test_rewrites_only_large_ms_values_to_seconds(self) -> None:
        assert replace_duration_ms_tokens("SELECT 1 took 1200ms (threshold: 500ms)") == (
            "SELECT 1 took 1.2s (threshold: 500ms)"
        )

    def test_preserves_sub_second_millisecond_tokens(self) -> None:
        assert replace_duration_ms_tokens("Prowlarr responded in 450ms") == (
            "Prowlarr responded in 450ms"
        )


class TestHealthParentheticalNextLine:
    def test_moves_parenthetical_segment_to_new_line(self) -> None:
        assert _health_parenthetical_next_line("85% used (4.1 GB free)") == (
            "85% used\n(4.1 GB free)"
        )

    def test_leaves_plain_text_unchanged(self) -> None:
        assert _health_parenthetical_next_line("All clear") == "All clear"
