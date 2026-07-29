"""Security and compatibility contracts for the native resolver client."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import structlog
from structlog.testing import capture_logs

if TYPE_CHECKING:
    from collections.abc import Sequence

import pullbox.providers.direct.resolver as resolver_module
from pullbox.providers.direct.resolver import (
    DirectResolverClient,
    DirectResolverError,
    ResolverCircuitBreaker,
    validate_resolver_target,
)

AUTH_SECRET = "resolver-auth-secret"
COOKIE_SECRET = "source-cookie-secret"


async def _resolve_public(_host: str, _port: int) -> Sequence[str]:
    return ["8.8.8.8"]


async def _resolve_private(_host: str, _port: int) -> Sequence[str]:
    return ["172.20.0.9"]


def _solution(*, url: str = "https://source.example/comics") -> dict[str, object]:
    return {
        "status": "ok",
        "message": "Challenge solved!",
        "solution": {
            "url": url,
            "status": 200,
            "headers": {"content-type": "text/html", "x-secret": "not-retained"},
            "response": "<html><title>Comics</title></html>",
            "cookies": [
                {
                    "name": "cf_clearance",
                    "value": COOKIE_SECRET,
                    "domain": ".source.example",
                    "path": "/",
                }
            ],
            "userAgent": "Resolver Browser",
        },
        "startTimestamp": 1,
        "endTimestamp": 2,
        "version": "3.5.0",
    }


async def test_resolver_posts_standard_v1_request_and_returns_ephemeral_solution() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://172.20.0.9:8191/v1"
        assert request.headers["Host"] == "resolver:8191"
        assert request.headers["Authorization"] == f"Bearer {AUTH_SECRET}"
        payload = json.loads(request.content)
        assert payload == {
            "cmd": "request.get",
            "url": "https://source.example/comics?issue=1",
            "maxTimeout": 60000,
        }
        return httpx.Response(200, json=_solution())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DirectResolverClient(
            endpoint="http://resolver:8191",
            allow_private_http=True,
            authentication_headers={"Authorization": f"Bearer {AUTH_SECRET}"},
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
        )
        result = await client.solve(
            "https://source.example/comics?issue=1",
            declared_domains=("source.example",),
            challenge_category="cloudflare",
        )

    assert result.final_url == "https://source.example/comics"
    assert result.status_code == 200
    assert result.html.startswith("<html>")
    assert result.user_agent == "Resolver Browser"
    assert result.cookies[0].name == "cf_clearance"
    assert AUTH_SECRET not in repr(client)
    assert COOKIE_SECRET not in repr(result)
    assert "x-secret" not in repr(result)


async def test_resolver_posts_trawl_native_scrape_request_and_returns_solution() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://172.20.0.9:8191/scrape"
        assert request.headers["Host"] == "trawl:8191"
        payload = json.loads(request.content)
        assert payload == {
            "url": "https://source.example/login",
            "maxTimeout": 60000,
            "skipHttp": True,
            "maxTier": 3,
        }
        return httpx.Response(
            200,
            json={
                "url": "https://source.example/login",
                "html": '<input name="cf-turnstile-response" value="solved-token">',
                "cookies": [
                    {
                        "name": "cf_clearance",
                        "value": COOKIE_SECRET,
                        "domain": ".source.example",
                        "path": "/",
                        "secure": True,
                    }
                ],
                "userAgent": "Trawl Browser",
                "statusCode": 200,
                "tier": 3,
                "sessionCached": False,
                "timings": [],
                "totalMs": 1250,
                "proxyUsed": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DirectResolverClient(
            endpoint="http://trawl:8191",
            allow_private_http=True,
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
        )
        result = await client.solve_trawl_native(
            "https://source.example/login",
            declared_domains=("source.example",),
            challenge_category="artifact_host_login",
        )

    assert result.final_url == "https://source.example/login"
    assert result.status_code == 200
    assert "solved-token" in result.html
    assert result.user_agent == "Trawl Browser"
    assert result.cookies[0].name == "cf_clearance"
    assert COOKIE_SECRET not in repr(result)


async def test_trawl_native_revalidates_returned_domain() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "url": "https://evil.example/escape",
                "html": "<html></html>",
                "cookies": [],
                "userAgent": "Trawl Browser",
                "statusCode": 200,
                "tier": 3,
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DirectResolverClient(
            endpoint="http://trawl:8191",
            allow_private_http=True,
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
        )
        with pytest.raises(DirectResolverError) as exc_info:
            await client.solve_trawl_native(
                "https://source.example/login",
                declared_domains=("source.example",),
                challenge_category="artifact_host_login",
            )

    assert exc_info.value.code == "resolver_redirect_rejected"


@pytest.mark.parametrize(
    ("url", "domains"),
    [
        ("https://evil.example/", ("source.example",)),
        ("https://source.example.evil.test/", ("source.example",)),
        ("https://user:pass@source.example/", ("source.example",)),
        ("ftp://source.example/file", ("source.example",)),
        ("https://127.0.0.1/admin", ("127.0.0.1",)),
    ],
)
async def test_resolver_target_must_stay_on_declared_public_domains(
    url: str,
    domains: tuple[str, ...],
) -> None:
    with pytest.raises(DirectResolverError):
        await validate_resolver_target(url, declared_domains=domains, resolver=_resolve_public)


async def test_resolver_revalidates_returned_redirect_domain() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=_solution(url="https://evil.example/escape"))
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DirectResolverClient(
            endpoint="http://resolver:8191",
            allow_private_http=True,
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
        )
        with pytest.raises(DirectResolverError) as exc_info:
            await client.solve(
                "https://source.example/comics",
                declared_domains=("source.example",),
                challenge_category="cloudflare",
            )

    assert exc_info.value.code == "resolver_redirect_rejected"


async def test_resolver_rejects_http_redirects_malformed_and_oversized_responses() -> None:
    cases = (
        (
            httpx.Response(302, headers={"Location": "http://169.254.169.254/"}),
            "resolver_redirect_rejected",
        ),
        (httpx.Response(200, content=b"not-json"), "resolver_malformed_response"),
        (
            httpx.Response(200, content=b"{" + b" " * (8 * 1024 * 1024) + b"}"),
            "resolver_response_too_large",
        ),
    )
    for response, code in cases:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request, value=response: value)
        ) as http_client:
            client = DirectResolverClient(
                endpoint="http://resolver:8191",
                allow_private_http=True,
                endpoint_resolver=_resolve_private,
                target_resolver=_resolve_public,
                http_client=http_client,
            )
            with pytest.raises(DirectResolverError) as exc_info:
                await client.solve(
                    "https://source.example/comics",
                    declared_domains=("source.example",),
                    challenge_category="cloudflare",
                )
            assert exc_info.value.code == code


async def test_resolver_preserves_cancellation_and_classifies_timeout() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return httpx.Response(200, json=_solution())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DirectResolverClient(
            endpoint="http://resolver:8191",
            allow_private_http=True,
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
            timeout_seconds=0.01,
        )
        with pytest.raises(DirectResolverError) as exc_info:
            await client.solve(
                "https://source.example/comics",
                declared_domains=("source.example",),
                challenge_category="cloudflare",
            )
        assert exc_info.value.code == "resolver_timed_out"

        task = asyncio.create_task(
            client.solve(
                "https://source.example/comics",
                declared_domains=("source.example",),
                challenge_category="cloudflare",
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_circuit_breaker_opens_recovers_and_does_not_queue_busy_requests() -> None:
    clock = [100.0]
    breaker = ResolverCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        max_concurrency=1,
        clock=lambda: clock[0],
    )

    await breaker.record_failure()
    assert breaker.state == "closed"
    await breaker.record_failure()
    assert breaker.state == "open"
    with pytest.raises(DirectResolverError, match="temporarily unavailable"):
        async with breaker.slot():
            pass

    clock[0] += 31
    async with breaker.slot():
        assert breaker.state == "half_open"
        with pytest.raises(DirectResolverError) as busy:
            async with breaker.slot():
                pass
        assert busy.value.code == "resolver_busy"
        await breaker.record_success()
    assert breaker.state == "closed"


async def test_resolver_logs_only_domain_category_and_classified_outcome() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=_solution()))
    structlog.reset_defaults()
    resolver_module.logger = structlog.get_logger(resolver_module.__name__)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DirectResolverClient(
            endpoint="http://resolver:8191",
            allow_private_http=True,
            authentication_headers={"Authorization": f"Bearer {AUTH_SECRET}"},
            endpoint_resolver=_resolve_private,
            target_resolver=_resolve_public,
            http_client=http_client,
        )
        with capture_logs() as logs:
            await client.solve(
                "https://source.example/comics?token=query-secret",
                declared_domains=("source.example",),
                challenge_category="cloudflare",
            )

    event = next(item for item in logs if item["event"] == "direct_resolver_request_completed")
    assert event["source_domain"] == "source.example"
    assert event["challenge_category"] == "cloudflare"
    assert event["outcome"] == "success"
    assert "query-secret" not in str(logs)
    assert AUTH_SECRET not in str(logs)
    assert COOKIE_SECRET not in str(logs)
