"""Client for the public pullbox-data release contract."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from pullbox import __version__
from pullbox.config import get_settings

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from datetime import date

JsonObject = dict[str, Any]

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25


class PullboxDataClientError(Exception):
    """Raised when pullbox-data cannot return a usable response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.cause = cause
        super().__init__(message)


class WhatsNewDataClient:
    """Small async client for upstream release and telemetry-adjacent data."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        configured_base_url = base_url or get_settings().pullbox_data_api_base_url
        self._base_url = configured_base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_attempts = max(1, max_attempts)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._transport = transport

    async def get_current_week(self, store_date: date | None = None) -> JsonObject:
        """Fetch current-week releases, optionally for a specific store date."""

        params = {"store_date": store_date.isoformat()} if store_date else None
        return await self._get_json(
            "/api/v1/releases",
            params=params,
        )

    async def get_upcoming(self, publisher: str | None = None) -> JsonObject:
        """Fetch upcoming release weeks, optionally filtered by publisher."""

        params = {"upcoming": "true"}
        if publisher:
            params["publisher"] = publisher
        return await self._get_json("/api/v1/releases", params=params)

    async def test_connection(self) -> JsonObject:
        """Verify that the upstream release endpoint is reachable."""

        await self._get_json("/api/v1/releases")
        return {"ok": True, "status_code": 200, "reachable": True}

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> JsonObject:
        url = f"{self._base_url}{path}"
        last_error: PullboxDataClientError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                    headers={"User-Agent": f"Pullbox/{__version__}"},
                ) as client:
                    response = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_error = PullboxDataClientError(
                    "Timed out while contacting pullbox-data.",
                    cause=exc,
                )
                await self._warn_and_pause(
                    attempt,
                    "pullbox_data_request_timeout",
                    url=url,
                    error=str(exc),
                )
                continue
            except httpx.TransportError as exc:
                last_error = PullboxDataClientError(
                    "Unable to contact pullbox-data.",
                    cause=exc,
                )
                await self._warn_and_pause(
                    attempt,
                    "pullbox_data_request_transport_error",
                    url=url,
                    error=str(exc),
                )
                continue

            if 200 <= response.status_code < 300:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise PullboxDataClientError("pullbox-data returned a non-object JSON payload.")
                return payload

            error = PullboxDataClientError(
                f"pullbox-data returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
            if not self._should_retry_status(response.status_code):
                logger.warning(
                    "pullbox_data_request_failed",
                    url=url,
                    status_code=response.status_code,
                    retryable=False,
                )
                raise error

            last_error = error
            await self._warn_and_pause(
                attempt,
                "pullbox_data_request_retryable_status",
                url=url,
                status_code=response.status_code,
            )

        if last_error is None:
            raise PullboxDataClientError("pullbox-data request failed.")
        raise last_error

    async def _warn_and_pause(self, attempt: int, event: str, **fields: Any) -> None:
        retrying = attempt < self._max_attempts
        logger.warning(event, attempt=attempt, retrying=retrying, **fields)
        if retrying and self._retry_backoff_seconds > 0:
            await asyncio.sleep(self._retry_backoff_seconds)

    @staticmethod
    def _should_retry_status(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599
