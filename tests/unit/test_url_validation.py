from __future__ import annotations

import pytest

from pullbox.core.url_validation import normalize_peer_base_url


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (" HTTP://Example.test:8080/base/ ", "http://Example.test:8080/base"),
        ("https://prowlarr.local/", "https://prowlarr.local"),
        ("https://indexer.local/api?apikey=redacted", "https://indexer.local/api?apikey=redacted"),
    ],
)
def test_normalize_peer_base_url_preserves_valid_http_urls(raw_url: str, expected: str) -> None:
    assert normalize_peer_base_url(raw_url) == expected


@pytest.mark.parametrize(
    ("raw_url", "message"),
    [
        ("https://example.test/has space", "URL must not contain whitespace."),
        ("ftp://example.test", "URL must use http or https."),
        ("https:///missing-host", "URL must include a host."),
        ("https://user:pass@example.test", "URL must not include embedded credentials."),
    ],
)
def test_normalize_peer_base_url_rejects_unsafe_or_incomplete_urls(
    raw_url: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_peer_base_url(raw_url)
