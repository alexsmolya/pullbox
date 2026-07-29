"""Transmission download client implementation.

Integrates with the Transmission RPC API to manage torrent downloads.
Implements the DownloadClient protocol with HTTP Basic auth, automatic
409 session-id negotiation, and structured logging.

Transmission RPC docs: https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from pullbox.core.config_resolver import resolve_runtime_service_url
from pullbox.providers.base import ClientOptions, DownloadStatus, ProviderHealthResult

logger = structlog.get_logger(__name__)

_REQUEST_TIMEOUT = 10.0

# Transmission status codes → normalized states
_STATUS_MAP: dict[int, str] = {
    0: "paused",  # Stopped
    1: "queued",  # Check pending
    2: "downloading",  # Checking
    3: "queued",  # Download pending
    4: "downloading",  # Downloading
    5: "completed",  # Seed pending
    6: "completed",  # Seeding
}

# Status codes that get a human-readable client_state label
_CLIENT_STATE_MAP: dict[int, str] = {
    2: "Checking",
}


class TransmissionError(Exception):
    """Raised when the Transmission RPC API returns an error."""


class TransmissionClient:
    """Transmission implementation of DownloadClient.

    Uses Transmission's RPC API with session-based CSRF protection.
    Automatically handles 409 session-id negotiation and HTTP Basic auth.

    Args:
        url: Base URL (e.g. ``http://localhost:9091``).
        username: RPC username (optional if auth disabled).
        password: RPC password.
        download_dir: Override download directory for added torrents.
        bandwidth_priority: -1=low, 0=normal, 1=high.
        seed_ratio_limit: Stop seeding at this ratio.
        seed_idle_limit: Stop seeding after idle for N minutes.
    """

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        download_dir: str | None = None,
        bandwidth_priority: int | None = None,
        seed_ratio_limit: float | None = None,
        seed_idle_limit: int | None = None,
    ) -> None:
        self._base_url = resolve_runtime_service_url(url).rstrip("/")
        self._rpc_url = f"{self._base_url}/transmission/rpc"
        self._download_dir = download_dir
        self._bandwidth_priority = bandwidth_priority
        self._seed_ratio_limit = seed_ratio_limit
        self._seed_idle_limit = seed_idle_limit
        self._session_id: str | None = None

        auth = None
        if username:
            auth = httpx.BasicAuth(username, password)
        self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, auth=auth)

    @property
    def name(self) -> str:
        return "transmission"

    @property
    def client_type(self) -> str:
        return "transmission"

    # -- RPC plumbing ----------------------------------------------------------

    async def _rpc(
        self,
        method: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Make an RPC call to Transmission.

        Automatically handles 409 session-id negotiation (retry once).
        """
        log = logger.bind(method=method)
        log.debug("transmission_rpc_call")

        payload: dict[str, Any] = {"method": method}
        if arguments:
            payload["arguments"] = arguments

        for attempt in range(2):
            headers: dict[str, str] = {}
            if self._session_id:
                headers["X-Transmission-Session-Id"] = self._session_id

            try:
                response = await self._client.post(
                    self._rpc_url,
                    json=payload,
                    headers=headers,
                )
            except httpx.TimeoutException:
                log.error("transmission_timeout")
                raise TransmissionError("Request timed out") from None
            except httpx.HTTPError as exc:
                log.error("transmission_request_failed", error=str(exc))
                raise TransmissionError(f"Request failed: {exc}") from None

            # 409 → extract session ID and retry
            if response.status_code == 409:
                new_id = response.headers.get("X-Transmission-Session-Id", "")
                if not new_id:
                    raise TransmissionError("409 without session ID header")
                self._session_id = new_id
                log.debug("transmission_session_id_refreshed")
                if attempt == 0:
                    continue
                raise TransmissionError("Session ID negotiation failed after retry")

            if response.status_code == 401:
                raise TransmissionError("Authentication failed — check username/password")

            if response.status_code >= 400:
                log.error("transmission_http_error", status=response.status_code)
                raise TransmissionError(f"HTTP {response.status_code}")

            data: dict[str, Any] = response.json()
            result_str = data.get("result", "")
            if result_str != "success":
                raise TransmissionError(f"RPC error: {result_str}")

            return data.get("arguments", {})

        raise TransmissionError("Request failed after retry")

    # -- DownloadClient implementation -----------------------------------------

    async def add_nzb(
        self,
        url: str,
        title: str,
        category: str | None = None,
    ) -> str:
        """Not supported — Transmission is torrent-only."""
        raise NotImplementedError("Transmission does not support NZB downloads")

    async def add_torrent(
        self,
        url: str,
        title: str,
        category: str | None = None,
    ) -> str:
        """Add a torrent or magnet URL. Returns the torrent hash.

        For magnet links, passes the URI directly via ``filename``.
        For .torrent URLs, downloads the content first and passes it
        as base64-encoded ``metainfo`` to avoid redirect/auth issues
        when the client can't reach the indexer directly.
        """
        log = logger.bind(title=title)
        log.info("transmission_add_torrent")

        arguments: dict[str, Any] = {}

        if url.lower().startswith("magnet:"):
            arguments["filename"] = url
        else:
            # Download .torrent file and pass as base64 content.
            # Prowlarr URLs may redirect to the actual indexer or even
            # to a magnet link — handle both cases.
            import base64

            try:
                async with httpx.AsyncClient(
                    timeout=_REQUEST_TIMEOUT,
                    follow_redirects=False,
                ) as http:
                    resolved_url = url
                    for _ in range(5):  # max redirects
                        resp = await http.get(resolved_url)
                        if resp.status_code in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location", "")
                            if location.lower().startswith("magnet:"):
                                # Redirect target is a magnet link
                                arguments["filename"] = location
                                break
                            resolved_url = location
                            continue
                        resp.raise_for_status()
                        arguments["metainfo"] = base64.standard_b64encode(
                            resp.content,
                        ).decode("ascii")
                        break
                    else:
                        raise TransmissionError("Too many redirects")
            except TransmissionError:
                raise
            except Exception as exc:
                raise TransmissionError(f"Failed to download torrent file: {exc}") from None

        return await self._submit_torrent(arguments, log)

    async def add_torrent_data(
        self,
        content: bytes,
        title: str,
        category: str | None = None,
    ) -> str:
        """Submit descriptor bytes fetched and validated by Pullbox."""
        import base64

        log = logger.bind(title=title)
        log.info("transmission_add_torrent_data")
        return await self._submit_torrent(
            {"metainfo": base64.standard_b64encode(content).decode("ascii")},
            log,
        )

    async def _submit_torrent(
        self,
        arguments: dict[str, Any],
        log: Any,
    ) -> str:
        if self._download_dir:
            arguments["download-dir"] = self._download_dir
        if self._bandwidth_priority is not None:
            arguments["bandwidthPriority"] = self._bandwidth_priority
        if self._seed_ratio_limit is not None:
            arguments["seedRatioLimit"] = self._seed_ratio_limit
            arguments["seedRatioMode"] = 1  # Use per-torrent limit
        if self._seed_idle_limit is not None:
            arguments["seedIdleLimit"] = self._seed_idle_limit
            arguments["seedIdleMode"] = 1  # Use per-torrent limit

        result: dict[str, Any] = await self._rpc("torrent-add", arguments)

        # Transmission returns either "torrent-added" or "torrent-duplicate"
        torrent_info = result.get("torrent-added") or result.get("torrent-duplicate")
        if not torrent_info:
            raise TransmissionError("No torrent hash returned from torrent-add")

        hash_string = str(torrent_info.get("hashString", ""))
        if not hash_string:
            raise TransmissionError("No torrent hash in response")

        # Normalize hash to lowercase
        hash_string = hash_string.lower()

        is_duplicate = "torrent-duplicate" in result
        if is_duplicate:
            log.info(
                "transmission_torrent_duplicate",
                hash=hash_string,
                hint="Torrent already exists in Transmission.",
            )
        else:
            log.info("transmission_torrent_added", hash=hash_string)

        return hash_string

    async def get_download_status(self, external_id: str) -> DownloadStatus:
        """Get status of a specific torrent by hash."""
        log = logger.bind(external_id=external_id)
        log.debug("transmission_get_status")

        result: dict[str, Any] = await self._rpc(
            "torrent-get",
            {
                "ids": [external_id],
                "fields": _TORRENT_FIELDS,
            },
        )
        torrents: list[dict[str, Any]] = result.get("torrents", [])

        if not torrents:
            raise TransmissionError(f"Torrent not found: {external_id}")

        return _map_torrent(torrents[0])

    async def get_queue(self) -> list[DownloadStatus]:
        """Get all torrents."""
        logger.debug("transmission_get_queue")

        result: dict[str, Any] = await self._rpc(
            "torrent-get",
            {
                "fields": _TORRENT_FIELDS,
            },
        )
        torrents: list[dict[str, Any]] = result.get("torrents", [])

        results = [_map_torrent(t) for t in torrents]
        logger.debug("transmission_queue_fetched", count=len(results))
        return results

    async def remove_download(
        self,
        external_id: str,
        delete_files: bool = False,
    ) -> bool:
        """Remove a torrent, optionally deleting downloaded files."""
        log = logger.bind(external_id=external_id, delete_files=delete_files)
        log.info("transmission_remove_download")

        try:
            await self._rpc(
                "torrent-remove",
                {
                    "ids": [external_id],
                    "delete-local-data": delete_files,
                },
            )
            log.info("transmission_torrent_removed")
            return True
        except TransmissionError:
            log.warning("transmission_remove_failed")
            return False

    async def test_connection(self) -> ProviderHealthResult:
        """Verify connectivity by fetching session info."""
        start = time.monotonic()
        try:
            result: dict[str, Any] = await self._rpc("session-get")
            elapsed_ms = (time.monotonic() - start) * 1000
            version = result.get("version", "unknown")
            return ProviderHealthResult(
                healthy=True,
                message=f"Transmission {version}",
                response_time_ms=elapsed_ms,
                details={"version": str(version)},
            )
        except TransmissionError as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProviderHealthResult(
                healthy=False,
                message=f"Transmission error: {exc}",
                response_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("transmission_test_connection_failed")
            return ProviderHealthResult(
                healthy=False,
                message=f"Connection failed: {exc}",
                response_time_ms=elapsed_ms,
            )

    async def get_options(self) -> ClientOptions:
        """Fetch download directory from Transmission session info.

        Transmission has no native categories — returns empty category
        list with the default download directory.
        """
        result: dict[str, Any] = await self._rpc("session-get")
        download_dir = result.get("download-dir", "")
        return ClientOptions(
            categories=[],
            download_directories=[download_dir] if download_dir else None,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TORRENT_FIELDS = [
    "hashString",
    "name",
    "status",
    "percentDone",
    "totalSize",
    "rateDownload",
    "eta",
    "downloadDir",
    "error",
    "errorString",
]


def _map_torrent(torrent: dict[str, Any]) -> DownloadStatus:
    """Map a Transmission torrent to a DownloadStatus DTO."""
    status_code = torrent.get("status", 0)
    error_code = torrent.get("error", 0)
    error_string = torrent.get("errorString", "")
    rate_download = torrent.get("rateDownload", 0)

    # Local error (error=3) overrides status → failed
    if error_code == 3:
        state = "failed"
        error_message: str | None = error_string or "Local error"
    else:
        state = _map_transmission_status(status_code)
        error_message = None

    progress = torrent.get("percentDone", 0.0)
    size_bytes = torrent.get("totalSize")
    speed_bytes = rate_download if rate_download else None

    # ETA: negative values mean unknown/not-applicable
    eta = torrent.get("eta", -1)
    eta_seconds = eta if isinstance(eta, int) and eta > 0 else None

    # Client state: stalled download or checking
    client_state: str | None = None
    if state == "downloading" and rate_download == 0 and status_code == 4:
        client_state = "Stalled"
    elif status_code in _CLIENT_STATE_MAP:
        client_state = _CLIENT_STATE_MAP[status_code]

    download_dir = torrent.get("downloadDir") or None

    return DownloadStatus(
        external_id=str(torrent.get("hashString", "")).lower(),
        title=torrent.get("name", "Unknown"),
        state=state,
        progress=progress,
        size_bytes=size_bytes,
        speed_bytes=speed_bytes,
        eta_seconds=eta_seconds,
        error_message=error_message,
        downloaded_path=download_dir,
        client_state=client_state,
    )


def _map_transmission_status(status: int) -> str:
    """Map Transmission status integer to normalized state."""
    return _STATUS_MAP.get(status, "queued")
