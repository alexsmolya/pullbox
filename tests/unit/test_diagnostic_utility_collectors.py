"""Tests for diagnostic utility-job collector helpers."""

from __future__ import annotations

from pullbox.services.diagnostic_utility_collectors import parse_utility_log_extra


def test_parse_utility_log_extra_returns_empty_dict_for_blank_values() -> None:
    assert parse_utility_log_extra(None) == {}
    assert parse_utility_log_extra("") == {}


def test_parse_utility_log_extra_returns_dict_payloads() -> None:
    assert parse_utility_log_extra('{"worker_id": 2, "stage": "convert"}') == {
        "worker_id": 2,
        "stage": "convert",
    }


def test_parse_utility_log_extra_preserves_non_dict_or_invalid_payloads() -> None:
    assert parse_utility_log_extra("[1, 2]") == "[1, 2]"
    assert parse_utility_log_extra("{not-json") == "{not-json"
