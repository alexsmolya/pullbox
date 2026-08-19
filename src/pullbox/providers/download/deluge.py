"""Deluge download client implementation.

Integrates with the Deluge Web JSON-RPC API to manage torrent downloads.
Implements the DownloadClient protocol with password-only authentication,
automatic session re-login, Label plugin support, and structured logging.

Deluge Web API docs: https://deluge.readthedocs.io/en/latest/reference/webapi.html
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

# Deluge state strings → normalized states
_STATE_MAP: dict[str, str] = {
    "Downloading": "downloading",
    "Seeding": "completed",
    "Paused": "paused",
    "Checking": "downloading",
    "Queued": "queued",
    "Error": "failed",
    "Moving": "downloading",
    "Allocating": "downloading",
}

# States that get a human-readable client_state label
_CLIENT_STATE_MAP: dict[str, str] = {
    "Checking": "Checking",
    "Moving": "Moving",
    "Allocating": "Allocating",
}

# Fields to request from Deluge for torrent status
_TORRENT_FIELDS = [
    "name",
    "state",
    "progress",
    "total_size",
    "download_payload_rate",
    "eta",
    "save_path",
    "message",
    "tracker_status",
]


class DelugeError(Exception):
    """Raised when the Deluge API returns an error."""


class DelugeClient:
    """Deluge implementation of DownloadClient.

    Uses Deluge's Web JSON-RPC API with password-only authentication.
    Automatically re-authenticates on session expiry.

    Args:
        url: Base URL of Deluge Web UI (e.g. ``http://localhost:8112``).
        password: Deluge Web UI password (default: "deluge").
        label: Label to apply via Label plugin (optional).
        max_ratio: Stop seeding at this ratio (optional).
        move_completed_path: Move completed torrents to this path (optional).
    """

    def __init__(
        self,
        url: str,
        password: str = "deluge",
        label: str | None = None,
        max_ratio: float | None = None,
        move_completed_path: str | None = None,
    ) -> None:
        self._base_url = resolve_runtime_service_url(url).rstrip("/")
        self._password = password
        self._label = label
        self._max_ratio = max_ratio
        self._move_completed_path = move_completed_path
        self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        self._authenticated = False
        self._request_id = 0

    @property
    def name(self) -> str:
        return "deluge"

    @property
    def client_type(self) -> str:
        return "deluge"

    # -- authentication --------------------------------------------------------

    async def _login(self) -> None:
        """Authenticate with the Deluge Web UI and connect to daemon."""
        log = logger.bind(url=self._base_url)
        log.debug("deluge_login")

        result = await self._rpc_raw("auth.login", [self._password])

        # Deluge < 2.0 may return None; treat as success if no error was raised
        if result is False:
            raise DelugeError("Authentication failed — check password")

        self._authenticated = True
        log.debug("deluge_login_success")

        # Ensure Web UI is connected to the daemon — required before
        # any core.* or daemon.* methods will work
        await self._ensure_daemon_connected()

    async def _ensure_daemon_connected(self) -> None:
        """Ensure the Web UI is connected to the Deluge daemon.

        Deluge Web UI requires an explicit web.connect call before
        core.* and daemon.* methods will work.
        """
        try:
            connected = await self._rpc_raw("web.connected")
            if connected:
                return
        except DelugeError:
            pass

        # Get available hosts and connect to the first one
        hosts: list[list[Any]] = await self._rpc_raw("web.get_hosts")
        if not hosts:
            raise DelugeError("No Deluge daemon hosts configured")

        host_id = hosts[0][0]
        await self._rpc_raw("web.connect", [host_id])
        logger.debug("deluge_daemon_connected", host_id=host_id)

    async def _ensure_auth(self) -> None:
        """Ensure we have a valid session, logging in if needed."""
        if not self._authenticated:
            await self._login()

    # -- JSON-RPC plumbing -----------------------------------------------------

    async def _rpc_raw(
        self,
        method: str,
        params: list[Any] | None = None,
    ) -> Any:
        """Make a raw JSON-RPC call without auth retry logic."""
        log = logger.bind(method=method)
        log.debug("deluge_rpc_call")

        # Overflow protection for request ID counter
        if self._request_id >= 2**31:
            self._request_id = 0

        payload: dict[str, Any] = {
            "method": method,
            "params": params or [],
            "id": self._request_id,
        }
        self._request_id += 1

        try:
            response = await self._client.post(
                f"{self._base_url}/json",
                json=payload,
            )
        except httpx.TimeoutException:
            log.error("deluge_timeout")
            raise DelugeError("Request timed out") from None
        except httpx.HTTPError as exc:
            log.error("deluge_request_failed", error=str(exc))
            raise DelugeError(f"Request failed: {exc}") from None

        if response.status_code >= 400:
            log.error("deluge_http_error", status=response.status_code)
            raise DelugeError(f"HTTP {response.status_code}")

        data: dict[str, Any] = response.json()

        error = data.get("error")
        if error:
            if isinstance(error, dict):
                error_msg = error.get("message", "Unknown error")
            else:
                error_msg = str(error)
            raise DelugeError(str(error_msg))

        return data.get("result")

    async def _rpc(
        self,
        method: str,
        params: list[Any] | None = None,
    ) -> Any:
        """Make a JSON-RPC call with automatic auth retry on session expiry."""
        await self._ensure_auth()

        try:
            return await self._rpc_raw(method, params)
        except DelugeError as exc:
            # Check for auth-related failures — retry once after re-login
            error_msg = str(exc).lower()
            if "not authenticated" in error_msg or "not connected" in error_msg:
                logger.debug("deluge_session_expired_retrying")
                self._authenticated = False
                await self._login()
                return await self._rpc_raw(method, params)
            raise

    # -- DownloadClient implementation -----------------------------------------

    async def add_nzb(
        self,
        url: str,
        title: str,
        category: str | None = None,
    ) -> str:
        """Not supported — Deluge is torrent-only."""
        raise NotImplementedError("Deluge does not support NZB downloads")

    async def add_torrent(
        self,
        url: str,
        title: str,
        category: str | None = None,
    ) -> str:
        """Add a torrent or magnet URL. Returns the torrent hash."""
        log = logger.bind(title=title)
        log.info("deluge_add_torrent")

        options: dict[str, Any] = {}
        if self._move_completed_path:
            options["move_completed"] = True
            options["move_completed_path"] = self._move_completed_path
        if self._max_ratio is not None:
            options["stop_at_ratio"] = True
            options["stop_ratio"] = self._max_ratio

        # Detect magnet vs URL
        if url.lower().startswith("magnet:"):
            result = await self._rpc("core.add_torrent_magnet", [url, options])
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
                    magnet_url: str | None = None
                    filedump = ""
                    for _ in range(5):  # max redirects
                        resp = await http.get(resolved_url)
                        if resp.status_code in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location", "")
                            if location.lower().startswith("magnet:"):
                                magnet_url = location
                                break
                            resolved_url = location
                            continue
                        resp.raise_for_status()
                        filedump = base64.standard_b64encode(
                            resp.content,
                        ).decode("ascii")
                        break
                    else:
                        raise DelugeError("Too many redirects")
            except DelugeError:
                raise
            except Exception as exc:
                raise DelugeError(f"Failed to download torrent file: {exc}") from None

            if magnet_url:
                result = await self._rpc(
                    "core.add_torrent_magnet",
                    [magnet_url, options],
                )
            else:
                torrent_name = f"{title}.torrent" if not title.endswith(".torrent") else title
                result = await self._rpc(
                    "core.add_torrent_file",
                    [torrent_name, filedump, options],
                )

        if not result:
            raise DelugeError(
                "Failed to add torrent — Deluge returned no hash (torrent may already exist)"
            )

        torrent_hash = str(result)
        log.info("deluge_torrent_added", hash=torrent_hash)

        # Apply label if configured
        if self._label:
            await self._apply_label(torrent_hash, self._label)

        return torrent_hash

    async def add_torrent_data(
        self,
        content: bytes,
        title: str,
        category: str | None = None,
    ) -> str:
        """Submit descriptor bytes fetched and validated by Pullbox."""
        import base64

        options: dict[str, Any] = {}
        if self._move_completed_path:
            options["move_completed"] = True
            options["move_completed_path"] = self._move_completed_path
        if self._max_ratio is not None:
            options["stop_at_ratio"] = True
            options["stop_ratio"] = self._max_ratio
        torrent_name = f"{title}.torrent" if not title.endswith(".torrent") else title
        result = await self._rpc(
            "core.add_torrent_file",
            [torrent_name, base64.standard_b64encode(content).decode("ascii"), options],
        )
        if not result:
            raise DelugeError(
                "Failed to add torrent - Deluge returned no hash (torrent may already exist)"
            )
        torrent_hash = str(result)
        if self._label:
            await self._apply_label(torrent_hash, self._label)
        logger.info("deluge_torrent_data_added", hash=torrent_hash, title=title)
        return torrent_hash

    async def _apply_label(self, torrent_hash: str, label: str) -> None:
        """Apply a label via the Label plugin, creating it if needed."""
        log = logger.bind(hash=torrent_hash, label=label)

        try:
            # Check if Label plugin is available and get existing labels
            existing: list[str] = await self._rpc("label.get_labels")

            # Create label if it doesn't exist
            if label not in existing:
                await self._rpc("label.add", [label])
                log.debug("deluge_label_created", label=label)

            # Set the label on the torrent
            await self._rpc("label.set_torrent", [torrent_hash, label])
            log.debug("deluge_label_set")

        except DelugeError as exc:
            # Label plugin not available — log warning but don't fail
            log.warning(
                "deluge_label_failed",
                error=str(exc),
                hint="Label plugin may not be enabled in Deluge.",
            )

    async def get_download_status(self, external_id: str) -> DownloadStatus:
        """Get status of a specific torrent by hash."""
        log = logger.bind(external_id=external_id)
        log.debug("deluge_get_status")

        result: dict[str, Any] = await self._rpc(
            "core.get_torrent_status",
            [external_id, _TORRENT_FIELDS],
        )

        if not result:
            raise DelugeError(f"Torrent not found: {external_id}")

        return _map_torrent(external_id, result)

    async def get_queue(self) -> list[DownloadStatus]:
        """Get all torrents."""
        logger.debug("deluge_get_queue")

        result: dict[str, dict[str, Any]] = await self._rpc(
            "core.get_torrents_status",
            [{}, _TORRENT_FIELDS],
        )

        if not result:
            return []

        results = [_map_torrent(h, data) for h, data in result.items()]
        logger.debug("deluge_queue_fetched", count=len(results))
        return results

    async def remove_download(
        self,
        external_id: str,
        delete_files: bool = False,
    ) -> bool:
        """Remove a torrent, optionally deleting downloaded files."""
        log = logger.bind(external_id=external_id, delete_files=delete_files)
        log.info("deluge_remove_download")

        try:
            await self._rpc(
                "core.remove_torrent",
                [external_id, delete_files],
            )
            log.info("deluge_torrent_removed")
            return True
        except DelugeError:
            log.warning("deluge_remove_failed")
            return False

    async def test_connection(self) -> ProviderHealthResult:
        """Verify connectivity by fetching the Deluge daemon version."""
        start = time.monotonic()
        try:
            await self._ensure_auth()
            version: str = await self._rpc("daemon.get_version")
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProviderHealthResult(
                healthy=True,
                message=f"Deluge {version}",
                response_time_ms=elapsed_ms,
                details={"version": str(version)},
            )
        except DelugeError as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProviderHealthResult(
                healthy=False,
                message=f"Deluge error: {exc}",
                response_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("deluge_test_connection_failed")
            return ProviderHealthResult(
                healthy=False,
                message=f"Connection failed: {exc}",
                response_time_ms=elapsed_ms,
            )

    async def get_options(self) -> ClientOptions:
        """Fetch available labels from the Deluge Label plugin."""
        try:
            labels: list[str] = await self._rpc("label.get_labels")
            return ClientOptions(
                categories=labels,
                extra={"label_plugin": True},
            )
        except DelugeError:
            logger.debug("deluge_label_plugin_unavailable")
            return ClientOptions(
                categories=[],
                extra={"label_plugin": False},
            )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _map_torrent(torrent_hash: str, data: dict[str, Any]) -> DownloadStatus:
    """Map a Deluge torrent status dict to a DownloadStatus DTO."""
    raw_state = data.get("state", "")
    state = _map_deluge_state(raw_state)

    # Deluge progress is 0-100 → normalize to 0.0-1.0
    progress = data.get("progress", 0.0) / 100.0

    size_bytes = data.get("total_size")

    # Use download_payload_rate (excludes protocol overhead)
    speed = data.get("download_payload_rate", 0)
    speed_bytes = speed if speed else None

    # ETA: 0, negative, or very large values mean unknown
    eta = data.get("eta", 0.0)
    if isinstance(eta, int | float) and eta > 0:
        eta_seconds: int | None = int(eta)
    else:
        eta_seconds = None

    # Error message from the message field
    error_message: str | None = None
    if state == "failed":
        error_message = data.get("message") or "Torrent error"

    # Client state for sub-phases
    client_state = _CLIENT_STATE_MAP.get(raw_state)

    save_path = data.get("save_path") or None

    return DownloadStatus(
        external_id=torrent_hash,
        title=data.get("name", "Unknown"),
        state=state,
        progress=progress,
        size_bytes=size_bytes,
        speed_bytes=speed_bytes,
        eta_seconds=eta_seconds,
        error_message=error_message,
        downloaded_path=save_path,
        client_state=client_state,
    )


def _map_deluge_state(state: str) -> str:
    """Map Deluge state string to normalized state."""
    return _STATE_MAP.get(state, state.lower())
