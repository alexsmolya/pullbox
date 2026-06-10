"""Tests for health placeholder check presenters."""

from __future__ import annotations


def test_download_client_placeholder_checks_use_existing_labels_and_unknown_state() -> None:
    from pullbox.ui.health_placeholder_checks import build_download_client_placeholder_checks

    checks = build_download_client_placeholder_checks()

    assert [check.name for check in checks] == [
        "Endpoint reachability",
        "Authentication",
        "Client identity",
        "Queue access",
    ]
    assert [check.key for check in checks] == [
        "placeholder-0",
        "placeholder-1",
        "placeholder-2",
        "placeholder-3",
    ]
    assert {check.status for check in checks} == {"unknown"}
    assert {check.response_label for check in checks} == {"—"}


def test_indexer_placeholder_checks_keep_distinct_proxy_and_indexer_labels() -> None:
    from pullbox.ui.health_placeholder_checks import (
        build_indexer_placeholder_checks,
        build_prowlarr_placeholder_checks,
    )

    prowlarr_checks = build_prowlarr_placeholder_checks()
    indexer_checks = build_indexer_placeholder_checks()

    assert [check.name for check in prowlarr_checks] == [
        "API connectivity",
        "Authentication",
        "Indexer registry",
        "Latency",
    ]
    assert next(check.key for check in prowlarr_checks) == "prowlarr-placeholder-0"
    assert [check.name for check in indexer_checks] == [
        "Endpoint reachability",
        "Authentication",
        "Capabilities",
        "Latency",
    ]
    assert next(check.key for check in indexer_checks) == "indexer-placeholder-0"
    assert {check.status_label for check in (*prowlarr_checks, *indexer_checks)} == {"Unknown"}
