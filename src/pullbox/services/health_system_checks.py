"""System-resource-specific health check implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pullbox.models.health import HealthStatus
from pullbox.services.health_helpers import (
    _STATUS_PRECEDENCE,
    _coerce_pathlike,
    _serialize_sub_check,
)
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pullbox.config import PullboxSettings

_FS_FREE_DEGRADED_GB = 50.0
_FS_FREE_UNHEALTHY_GB = 10.0
_FS_FREE_DEGRADED_PCT = 10.0
_FS_FREE_UNHEALTHY_PCT = 3.0
_SYSTEM_CPU_LOAD_DEGRADED = 0.9
_SYSTEM_CPU_LOAD_UNHEALTHY = 1.25
_SYSTEM_MEMORY_AVAILABLE_DEGRADED_GB = 2.0
_SYSTEM_MEMORY_AVAILABLE_UNHEALTHY_GB = 1.0
_SYSTEM_SWAP_DEGRADED_PCT = 25.0
_SYSTEM_SWAP_UNHEALTHY_PCT = 50.0
_SYSTEM_SWAP_DEGRADED_GB = 1.0
_SYSTEM_SWAP_UNHEALTHY_GB = 4.0


async def check_system_resources(
    settings: PullboxSettings | None,
    *,
    check_cpu: Callable[[], Awaitable[tuple[SubCheckOutcome, str]]],
    check_memory: Callable[[], Awaitable[tuple[SubCheckOutcome, str]]],
    check_swap: Callable[[], Awaitable[tuple[SubCheckOutcome, str]]],
    check_disk: Callable[[Path, str], Awaitable[tuple[SubCheckOutcome, str]]],
) -> CheckOutcome:
    """Check host-level CPU, memory, swap, and disk pressure."""
    disk_path, disk_path_source = _resolve_system_disk_path(settings)

    resource_checks = [
        await check_cpu(),
        await check_memory(),
        await check_swap(),
        await check_disk(disk_path, disk_path_source),
    ]
    sub_checks = [check for check, _guidance in resource_checks]
    guidance_parts = [guidance for _check, guidance in resource_checks if guidance]
    worst_status = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )

    critical_checks = [check.name for check in sub_checks if check.status == HealthStatus.UNHEALTHY]
    warning_checks = [check.name for check in sub_checks if check.status == HealthStatus.DEGRADED]

    if "Disk pressure" in critical_checks:
        msg = "Disk pressure critical"
    elif "Memory pressure" in critical_checks:
        msg = "Memory pressure critical"
    elif "CPU load" in critical_checks:
        msg = "CPU load elevated"
    elif "Swap pressure" in critical_checks:
        msg = "Swap pressure elevated"
    elif warning_checks:
        msg = "Resources running hot"
    else:
        msg = "Resources normal"

    return CheckOutcome(
        component="system",
        check_name="resources",
        status=worst_status,
        message=msg,
        details={"checks": [_serialize_sub_check(check) for check in sub_checks]},
        actionable_guidance=" ".join(dict.fromkeys(guidance_parts)),
        sub_checks=tuple(sub_checks),
    )


def _resolve_system_disk_path(settings: PullboxSettings | None) -> tuple[Path, str]:
    """Return the user-storage path that system disk pressure should monitor."""
    configured_library_root = _coerce_pathlike(
        getattr(settings, "library_root", None) if settings else None
    )
    if configured_library_root is not None:
        return configured_library_root, "library_root"

    configured_data_dir = _coerce_pathlike(
        getattr(settings, "data_dir", None) if settings else None
    )
    if configured_data_dir is not None:
        return configured_data_dir, "data_dir"

    return Path.cwd(), "working_directory"


async def check_system_cpu(
    *,
    cpu_count: Callable[[], Any],
    getloadavg: Callable[[], tuple[float, float, float]],
    cpu_percent: Callable[[float], Any],
    os_cpu_count: Callable[[], int | None],
) -> tuple[SubCheckOutcome, str]:
    """Measure sustained CPU pressure using normalized load when available."""
    try:
        raw_cpu_count = await asyncio.to_thread(cpu_count)
        cpu_count_value = int(raw_cpu_count or os_cpu_count() or 1)
        cpu_count_value = max(cpu_count_value, 1)
        load1, load5, _load15 = await asyncio.to_thread(getloadavg)
        normalized_load = float(load5) / cpu_count_value
        details = {
            "cpu_count": cpu_count_value,
            "load_1m": round(float(load1), 2),
            "load_5m": round(float(load5), 2),
            "normalized_load": round(normalized_load, 2),
        }
        if normalized_load >= _SYSTEM_CPU_LOAD_UNHEALTHY:
            return (
                SubCheckOutcome(
                    check_name="cpu_load",
                    name="CPU load",
                    status=HealthStatus.UNHEALTHY,
                    message=f"{normalized_load:.2f} load/core (5m avg, {cpu_count_value} cores)",
                    details=details,
                ),
                (
                    "CPU load is saturating available cores. Check for runaway jobs "
                    "or reduce concurrent workload."
                ),
            )
        if normalized_load >= _SYSTEM_CPU_LOAD_DEGRADED:
            return (
                SubCheckOutcome(
                    check_name="cpu_load",
                    name="CPU load",
                    status=HealthStatus.DEGRADED,
                    message=f"{normalized_load:.2f} load/core (5m avg, {cpu_count_value} cores)",
                    details=details,
                ),
                "CPU load is elevated. Monitor background jobs and host contention.",
            )
        return (
            SubCheckOutcome(
                check_name="cpu_load",
                name="CPU load",
                status=HealthStatus.HEALTHY,
                message=f"{normalized_load:.2f} load/core (5m avg, {cpu_count_value} cores)",
                details=details,
            ),
            "",
        )
    except (AttributeError, OSError):
        try:
            cpu_pct = float(await asyncio.to_thread(cpu_percent, 0.1))
        except OSError as exc:
            return (
                SubCheckOutcome(
                    check_name="cpu_load",
                    name="CPU load",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Cannot read CPU load ({exc})",
                ),
                "Host CPU telemetry is unavailable. Check host permissions and psutil support.",
            )
        cpu_percent_details: dict[str, Any] = {
            "cpu_percent": round(cpu_pct, 1),
            "sample": "instant",
        }
        if cpu_pct >= 95:
            status = HealthStatus.UNHEALTHY
            guidance = (
                "CPU usage is critically high. Check for runaway jobs or reduce "
                "concurrent workload."
            )
        elif cpu_pct >= 80:
            status = HealthStatus.DEGRADED
            guidance = "CPU usage is elevated. Monitor host load and background jobs."
        else:
            status = HealthStatus.HEALTHY
            guidance = ""
        return (
            SubCheckOutcome(
                check_name="cpu_load",
                name="CPU load",
                status=status,
                message=f"{cpu_pct:.0f}% busy (instant sample)",
                details=cpu_percent_details,
            ),
            guidance,
        )


async def check_system_memory(
    *,
    virtual_memory: Callable[[], Any],
) -> tuple[SubCheckOutcome, str]:
    """Measure memory pressure using percent used and available RAM."""
    try:
        mem = await asyncio.to_thread(virtual_memory)
    except OSError as exc:
        return (
            SubCheckOutcome(
                check_name="memory_pressure",
                name="Memory pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot read memory ({exc})",
            ),
            "Host memory telemetry is unavailable. Check host permissions and psutil support.",
        )

    mem_pct = float(mem.percent)
    avail_gb = mem.available / (1024**3)
    details = {
        "used_pct": round(mem_pct, 1),
        "available_gb": round(avail_gb, 1),
        "total_gb": round(mem.total / (1024**3), 1),
    }
    if mem_pct >= 95 or avail_gb < _SYSTEM_MEMORY_AVAILABLE_UNHEALTHY_GB:
        return (
            SubCheckOutcome(
                check_name="memory_pressure",
                name="Memory pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"{mem_pct:.0f}% used ({avail_gb:.1f} GB available)",
                details=details,
            ),
            (
                "Available memory is critically low. Reduce memory-heavy work or "
                "increase host memory."
            ),
        )
    if mem_pct >= 80 or avail_gb < _SYSTEM_MEMORY_AVAILABLE_DEGRADED_GB:
        return (
            SubCheckOutcome(
                check_name="memory_pressure",
                name="Memory pressure",
                status=HealthStatus.DEGRADED,
                message=f"{mem_pct:.0f}% used ({avail_gb:.1f} GB available)",
                details=details,
            ),
            "Memory pressure is elevated. Monitor active jobs and consider freeing RAM.",
        )
    return (
        SubCheckOutcome(
            check_name="memory_pressure",
            name="Memory pressure",
            status=HealthStatus.HEALTHY,
            message=f"{mem_pct:.0f}% used ({avail_gb:.1f} GB available)",
            details=details,
        ),
        "",
    )


async def check_system_swap(
    *,
    swap_memory: Callable[[], Any],
) -> tuple[SubCheckOutcome, str]:
    """Measure swap activity as a supporting memory-pressure signal."""
    try:
        swap = await asyncio.to_thread(swap_memory)
    except OSError as exc:
        return (
            SubCheckOutcome(
                check_name="swap_pressure",
                name="Swap pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot read swap ({exc})",
            ),
            "Host swap telemetry is unavailable. Check host permissions and psutil support.",
        )

    used_gb = swap.used / (1024**3)
    total_gb = swap.total / (1024**3)
    swap_pct = float(swap.percent)
    details = {
        "used_gb": round(used_gb, 1),
        "total_gb": round(total_gb, 1),
        "used_pct": round(swap_pct, 1),
    }
    if swap.total <= 0:
        return (
            SubCheckOutcome(
                check_name="swap_pressure",
                name="Swap pressure",
                status=HealthStatus.HEALTHY,
                message="Swap not configured",
                details=details,
            ),
            "",
        )
    if swap_pct >= _SYSTEM_SWAP_UNHEALTHY_PCT or used_gb >= _SYSTEM_SWAP_UNHEALTHY_GB:
        return (
            SubCheckOutcome(
                check_name="swap_pressure",
                name="Swap pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"{swap_pct:.0f}% used ({used_gb:.1f} GB in use)",
                details=details,
            ),
            (
                "Swap usage is critically high, which usually means memory "
                "pressure is spilling to disk."
            ),
        )
    if swap_pct >= _SYSTEM_SWAP_DEGRADED_PCT or used_gb >= _SYSTEM_SWAP_DEGRADED_GB:
        return (
            SubCheckOutcome(
                check_name="swap_pressure",
                name="Swap pressure",
                status=HealthStatus.DEGRADED,
                message=f"{swap_pct:.0f}% used ({used_gb:.1f} GB in use)",
                details=details,
            ),
            "Swap usage is elevated. Monitor memory-heavy workloads and host pressure.",
        )
    return (
        SubCheckOutcome(
            check_name="swap_pressure",
            name="Swap pressure",
            status=HealthStatus.HEALTHY,
            message=f"{swap_pct:.0f}% used ({used_gb:.1f} GB in use)",
            details=details,
        ),
        "",
    )


async def check_system_disk(
    disk_path: Path,
    *,
    path_source: str,
    disk_usage: Callable[[Path], Any],
) -> tuple[SubCheckOutcome, str]:
    """Measure host disk pressure for the active data path."""
    try:
        usage = await asyncio.to_thread(disk_usage, disk_path)
    except OSError as exc:
        return (
            SubCheckOutcome(
                check_name="disk_pressure",
                name="Disk pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot read disk usage ({exc})",
                details={"path": str(disk_path), "path_source": path_source},
            ),
            "Disk usage could not be read. Check the data mount and host filesystem status.",
        )

    free_gb = usage.free / (1024**3)
    free_pct = (usage.free / usage.total) * 100 if usage.total else 0.0
    used_pct = (usage.used / usage.total) * 100 if usage.total else 0.0
    details = {
        "path": str(disk_path),
        "path_source": path_source,
        "free_gb": round(free_gb, 1),
        "free_pct": round(free_pct, 1),
        "used_pct": round(used_pct, 1),
        "total_gb": round(usage.total / (1024**3), 1),
    }
    if free_gb < _FS_FREE_UNHEALTHY_GB or free_pct < _FS_FREE_UNHEALTHY_PCT:
        return (
            SubCheckOutcome(
                check_name="disk_pressure",
                name="Disk pressure",
                status=HealthStatus.UNHEALTHY,
                message=f"{used_pct:.0f}% used ({free_gb:.1f} GB free)",
                details=details,
            ),
            (
                "Disk space is critically low on the active data volume. Free "
                "space immediately to avoid write failures."
            ),
        )
    if free_gb < _FS_FREE_DEGRADED_GB or free_pct < _FS_FREE_DEGRADED_PCT:
        return (
            SubCheckOutcome(
                check_name="disk_pressure",
                name="Disk pressure",
                status=HealthStatus.DEGRADED,
                message=f"{used_pct:.0f}% used ({free_gb:.1f} GB free)",
                details=details,
            ),
            (
                "Disk space is running low on the active data volume. Consider "
                "freeing space or expanding the volume."
            ),
        )
    return (
        SubCheckOutcome(
            check_name="disk_pressure",
            name="Disk pressure",
            status=HealthStatus.HEALTHY,
            message=f"{used_pct:.0f}% used ({free_gb:.1f} GB free)",
            details=details,
        ),
        "",
    )
