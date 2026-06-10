"""Mylar3 database auto-detection for collection import.

Best-effort helper that searches for mylar.db on the local system via
Docker container inspection and common filesystem paths. Failures silently
return empty results — the import feature works fine if nothing is found.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_SUBPROCESS_TIMEOUT = 5.0  # seconds


def _mylar_extract_path(container: str) -> str:
    """Return a safe temporary destination for docker-copied Mylar databases."""
    safe_container = re.sub(r"[^A-Za-z0-9_.-]+", "_", container).strip("._") or "container"
    return str(Path(tempfile.gettempdir()) / f"pullbox_mylar_{safe_container}.db")


@dataclass
class Mylar3DbCandidate:
    """A detected Mylar3 database location."""

    path: str
    source: str  # "docker_bind_mount" | "docker_named_volume" | "filesystem"
    label: str
    container_name: str | None = None
    note: str | None = None
    ready: bool = True
    path_map: dict[str, str] = field(default_factory=dict)


async def locate_mylar3_db() -> list[Mylar3DbCandidate]:
    """Attempt to locate mylar.db on the local system.

    Searches Docker first (highest confidence), then filesystem.
    Returns deduplicated list by resolved path. Never raises.
    """
    candidates: list[Mylar3DbCandidate] = []
    candidates.extend(await _find_via_docker())
    candidates.extend(await _find_via_filesystem())

    # Deduplicate by resolved path
    seen: set[str] = set()
    unique: list[Mylar3DbCandidate] = []
    for c in candidates:
        try:
            resolved = str(Path(c.path).resolve())
        except Exception:
            resolved = c.path
        if resolved not in seen:
            seen.add(resolved)
            unique.append(c)

    logger.info("mylar3_locate_completed", candidates=len(unique))
    return unique


async def _run_command(*args: str) -> str | None:
    """Run a subprocess command with timeout. Returns stdout or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT)
        if proc.returncode != 0:
            return None
        return stdout.decode("utf-8", errors="replace").strip()
    except FileNotFoundError:
        return None
    except (TimeoutError, OSError):
        return None


async def _find_via_docker() -> list[Mylar3DbCandidate]:
    """Search Docker containers for Mylar3 installations."""
    results: list[Mylar3DbCandidate] = []

    try:
        # List running containers
        output = await _run_command("docker", "ps", "--format", "{{.Names}}\t{{.Image}}")
        if not output:
            return results

        # Find Mylar3 containers
        mylar_containers: list[str] = []
        for line in output.splitlines():
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            name, image = parts
            if "mylar" in name.lower() or "mylar" in image.lower():
                mylar_containers.append(name)

        # Inspect each Mylar3 container
        for container in mylar_containers:
            inspect_output = await _run_command("docker", "inspect", container)
            if not inspect_output:
                continue

            try:
                data = json.loads(inspect_output)
                if not data:
                    continue
                mounts = data[0].get("Mounts", [])
            except (json.JSONDecodeError, IndexError, KeyError):
                continue

            # Find /config mount
            config_mount = next(
                (m for m in mounts if m.get("Destination") == "/config"),
                None,
            )

            # Build path_map from other bind mounts
            path_map: dict[str, str] = {}
            for mount in mounts:
                dest = mount.get("Destination", "")
                if dest != "/config" and mount.get("Type") == "bind":
                    path_map[dest] = mount.get("Source", "")

            if config_mount and config_mount.get("Type") == "bind":
                host_path = Path(config_mount["Source"])
                db_path = host_path / "mylar.db"
                if db_path.exists():
                    results.append(
                        Mylar3DbCandidate(
                            path=str(db_path),
                            source="docker_bind_mount",
                            label=f"Docker ({container}) \u2014 {db_path}",
                            container_name=container,
                            ready=True,
                            path_map=path_map,
                        )
                    )
                else:
                    results.append(
                        Mylar3DbCandidate(
                            path=str(db_path),
                            source="docker_bind_mount",
                            label=f"Docker ({container}) \u2014 {host_path} (mylar.db not found)",
                            container_name=container,
                            note=(
                                f"mylar.db not found at {db_path}. "
                                "Start Mylar3 at least once first."
                            ),
                            ready=False,
                            path_map=path_map,
                        )
                    )
            elif config_mount and config_mount.get("Type") == "volume":
                extract_path = _mylar_extract_path(container)
                results.append(
                    Mylar3DbCandidate(
                        path=extract_path,
                        source="docker_named_volume",
                        label=f"Docker ({container}) \u2014 named volume (extraction required)",
                        container_name=container,
                        note=(
                            f"Run this command first, then click Refresh:\n"
                            f"docker cp {container}:/config/mylar.db {extract_path}"
                        ),
                        ready=False,
                        path_map=path_map,
                    )
                )
            elif not config_mount:
                extract_path = _mylar_extract_path(container)
                results.append(
                    Mylar3DbCandidate(
                        path=extract_path,
                        source="docker_named_volume",
                        label=f"Docker ({container}) \u2014 config location unknown",
                        container_name=container,
                        note=(
                            f"Run this command first, then click Refresh:\n"
                            f"docker cp {container}:/config/mylar.db {extract_path}"
                        ),
                        ready=False,
                        path_map=path_map,
                    )
                )

    except Exception:
        logger.debug("mylar3_docker_search_failed", exc_info=True)

    return results


async def _find_via_filesystem() -> list[Mylar3DbCandidate]:
    """Check known Mylar3 install locations on the local filesystem."""
    home = Path.home()

    candidate_paths = [
        # Docker bind mount conventions
        home / "docker" / "mylar3" / "mylar.db",
        home / "appdata" / "mylar3" / "mylar.db",
        home / "data" / "mylar3" / "mylar.db",
        Path("/opt/appdata/mylar3/mylar.db"),
        Path("/opt/docker/mylar3/mylar.db"),
        Path("/srv/docker/mylar3/mylar.db"),
        Path("/mnt/user/appdata/mylar3/mylar.db"),
        Path("/volume1/docker/mylar3/mylar.db"),
        Path("/volume1/data/mylar3/mylar.db"),
        Path("/config/mylar.db"),
        # Bare metal / git clone
        home / ".mylar" / "mylar.db",
        home / "mylar3" / "mylar.db",
        home / ".config" / "mylar3" / "mylar.db",
        Path("/opt/mylar3/mylar.db"),
        Path("/opt/mylar/mylar.db"),
        Path("/usr/local/mylar3/mylar.db"),
        # macOS
        home / "Library" / "Application Support" / "Mylar3" / "mylar.db",
        home / "Library" / "Application Support" / "mylar3" / "mylar.db",
    ]

    glob_patterns = [
        "/mnt/*/mylar3/mylar.db",
        "/mnt/*/mylar/mylar.db",
        "/srv/*/mylar3/mylar.db",
        "/media/*/mylar3/mylar.db",
        str(home / "docker" / "*" / "mylar.db"),
    ]

    def _check_paths() -> list[Mylar3DbCandidate]:
        import glob

        found: list[Mylar3DbCandidate] = []
        for path in candidate_paths:
            if path.exists():
                found.append(
                    Mylar3DbCandidate(
                        path=str(path),
                        source="filesystem",
                        label=str(path),
                        ready=True,
                    )
                )
        for pattern in glob_patterns:
            for match in glob.glob(pattern):
                p = Path(match)
                if p.exists() and p.name == "mylar.db":
                    found.append(
                        Mylar3DbCandidate(
                            path=str(p),
                            source="filesystem",
                            label=str(p),
                            ready=True,
                        )
                    )
        return found

    try:
        return await asyncio.to_thread(_check_paths)
    except Exception:
        logger.debug("mylar3_filesystem_search_failed", exc_info=True)
        return []
