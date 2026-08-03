from __future__ import annotations

import pytest

from pullbox.providers.artifact_hosts.contract import ArtifactHostResolutionError
from pullbox.providers.artifact_hosts.datanodes import _reject_challenge
from pullbox.providers.artifact_hosts.html import parse_host_page


@pytest.mark.parametrize(
    "source",
    [
        "https://challenges.cloudflare.com/turnstile/v0/api.js",
        "https://assets.hcaptcha.com/captcha/v1/index.html",
    ],
)
def test_datanodes_detects_challenge_iframe_by_hostname(source: str) -> None:
    parsed = parse_host_page(f'<iframe src="{source}"></iframe>')

    with pytest.raises(ArtifactHostResolutionError) as caught:
        _reject_challenge(parsed)

    assert caught.value.code == "artifact_host_challenge"


@pytest.mark.parametrize(
    "source",
    [
        "https://example.test/?next=challenges.cloudflare.com",
        "https://hcaptcha.com.evil.example/captcha",
    ],
)
def test_datanodes_does_not_match_challenge_domain_outside_hostname_boundary(
    source: str,
) -> None:
    parsed = parse_host_page(f'<iframe src="{source}"></iframe>')

    _reject_challenge(parsed)
