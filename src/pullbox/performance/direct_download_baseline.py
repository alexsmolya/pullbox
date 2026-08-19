"""Deterministic workload runner for direct-download readiness baselines."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pullbox.performance.baseline import collect_context, summarize_numbers

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass(frozen=True)
class WorkloadSpec:
    """One deterministic benchmark command and the counters it exposes."""

    workload_id: str
    description: str
    command: tuple[str, ...]
    numeric_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandSample:
    """Result of one isolated benchmark command execution."""

    report: dict[str, object] | None
    wall_elapsed_ms: float
    error: str | None = None


class SampleRunner(Protocol):
    """Callable used to execute one benchmark sample."""

    def __call__(
        self,
        workload: WorkloadSpec,
        repo_root: Path,
        timeout_seconds: float,
    ) -> CommandSample: ...


def extract_json_report(output: str) -> dict[str, object]:
    """Extract the first complete JSON object from benchmark stdout."""

    decoder = json.JSONDecoder()
    for offset, character in enumerate(output):
        if character != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(output[offset:])
        except json.JSONDecodeError:
            continue
        if output[offset + end :].strip():
            continue
        if isinstance(parsed, dict):
            return parsed
    msg = "benchmark output did not contain a JSON object"
    raise ValueError(msg)


def _numeric_values(
    samples: Sequence[CommandSample],
    field: str,
) -> list[float]:
    values: list[float] = []
    for sample in samples:
        if sample.report is None:
            continue
        value = sample.report.get(field)
        if isinstance(value, int | float) and not isinstance(value, bool):
            values.append(float(value))
    return values


def summarize_workload(
    workload: WorkloadSpec,
    samples: Sequence[CommandSample],
) -> dict[str, object]:
    """Summarize successful samples while retaining every failure reason."""

    valid_samples: list[CommandSample] = []
    failures: list[str] = []
    for sample in samples:
        if sample.report is None:
            failures.append(sample.error or "benchmark returned no report")
            continue
        missing = [field for field in workload.required_fields if field not in sample.report]
        if missing:
            failures.append(f"benchmark report missing required fields: {', '.join(missing)}")
            continue
        elapsed = sample.report.get("elapsed_ms")
        if not isinstance(elapsed, int | float) or isinstance(elapsed, bool):
            failures.append("benchmark report missing numeric elapsed_ms")
            continue
        valid_samples.append(sample)

    elapsed_values = _numeric_values(valid_samples, "elapsed_ms")
    wall_values = [sample.wall_elapsed_ms for sample in valid_samples]
    peak_rss_values = _numeric_values(valid_samples, "peak_rss_bytes")
    metrics: dict[str, dict[str, float | int]] = {}
    for field in workload.numeric_fields:
        values = _numeric_values(valid_samples, field)
        if values:
            metrics[field] = summarize_numbers(values)

    return {
        "workload_id": workload.workload_id,
        "description": workload.description,
        "command": [sys.executable, *workload.command],
        "samples_requested": len(samples),
        "samples_completed": len(valid_samples),
        "failure_count": len(failures),
        "failures": failures,
        "timing_ms": summarize_numbers(elapsed_values) if elapsed_values else None,
        "wall_timing_ms": summarize_numbers(wall_values) if wall_values else None,
        "peak_rss_bytes": summarize_numbers(peak_rss_values) if peak_rss_values else None,
        "metrics": metrics,
        "sample_reports": [sample.report for sample in valid_samples],
    }


def run_command_sample(
    workload: WorkloadSpec,
    repo_root: Path,
    timeout_seconds: float,
) -> CommandSample:
    """Run one benchmark in an isolated child process."""

    started_at = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, *workload.command],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        return CommandSample(
            report=None,
            wall_elapsed_ms=elapsed_ms,
            error=f"timed out after {timeout_seconds:g}s",
        )
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        return CommandSample(
            report=None,
            wall_elapsed_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        return CommandSample(
            report=None,
            wall_elapsed_ms=elapsed_ms,
            error=f"exit {result.returncode}: {detail}",
        )
    try:
        report = extract_json_report(result.stdout)
    except ValueError as exc:
        return CommandSample(report=None, wall_elapsed_ms=elapsed_ms, error=str(exc))
    return CommandSample(report=report, wall_elapsed_ms=elapsed_ms)


def default_workloads(*, profile: str) -> tuple[WorkloadSpec, ...]:
    """Return the closed, offline workload set for DD-0 measurements."""

    if profile not in {"quick", "standard"}:
        msg = f"unsupported benchmark profile: {profile}"
        raise ValueError(msg)
    quick = profile == "quick"
    scan_series, scan_files = (1, 1) if quick else (20, 4)
    import_series, import_files = (1, 3) if quick else (10, 3)
    search_results = 25 if quick else 100
    progress_updates = 100 if quick else 10_000
    transfer_size = 1 if quick else 256

    return (
        WorkloadSpec(
            workload_id="manual_issue_search",
            description="Deep manual issue-search core with mixed torrent/Usenet fan-out",
            command=(
                "scripts/benchmark_issue_search.py",
                "--mode",
                "deep",
                "--indexer-count",
                "2",
                "--result-count",
                str(search_results),
            ),
            numeric_fields=(
                "query_count",
                "indexer_request_count",
                "raw_results_count",
                "matched_count",
                "rejected_count",
            ),
            required_fields=("final_status", "query_count"),
        ),
        WorkloadSpec(
            workload_id="automated_issue_search_core",
            description=(
                "Fast per-target search core shared by search-on-add and wanted search; "
                "scheduler persistence is outside this synthetic probe"
            ),
            command=(
                "scripts/benchmark_issue_search.py",
                "--mode",
                "fast",
                "--indexer-count",
                "2",
                "--result-count",
                str(search_results),
            ),
            numeric_fields=(
                "query_count",
                "indexer_request_count",
                "raw_results_count",
                "matched_count",
                "rejected_count",
            ),
            required_fields=("final_status", "query_count"),
        ),
        WorkloadSpec(
            workload_id="import_scan_and_match",
            description="Step 2 archive inspection, parsing, series matching, and issue matching",
            command=(
                "scripts/benchmark_import_scan.py",
                "--series-count",
                str(scan_series),
                "--files-per-series",
                str(scan_files),
            ),
            numeric_fields=(
                "db_commit_count",
                "provider_search_calls",
                "provider_get_series_calls",
                "provider_issue_summary_calls",
                "provider_issue_number_calls",
                "archive_entry_issue_hint_count",
            ),
            required_fields=("final_status", "total_files_matched"),
        ),
        WorkloadSpec(
            workload_id="archive_post_processing",
            description="Step 4 mixed CBZ/CBR/CB7 conversion, metadata, and registration",
            command=(
                "scripts/benchmark_import_execute.py",
                "--series-count",
                str(import_series),
                "--files-per-series",
                str(import_files),
                "--file-work-profile",
                "mixed-small",
            ),
            numeric_fields=(
                "commit_count",
                "prefetch_calls",
                "series_add_calls",
                "library_file_count",
            ),
            required_fields=("final_status", "total_files_imported"),
        ),
        WorkloadSpec(
            workload_id="download_progress_updates",
            description="Transient download progress update cost and durable-write cadence",
            command=(
                "scripts/benchmark_download_progress.py",
                "--updates",
                str(progress_updates),
            ),
            numeric_fields=(
                "progress_update_count",
                "in_memory_write_count",
                "database_write_count",
                "updates_per_second",
            ),
            required_fields=("final_status", "database_write_count"),
        ),
        WorkloadSpec(
            workload_id="local_file_transfer",
            description="Existing local copy throughput and progress callback behavior",
            command=(
                "scripts/benchmark_file_transfer.py",
                "--size-mib",
                str(transfer_size),
            ),
            numeric_fields=(
                "bytes_transferred",
                "throughput_mib_per_second",
                "progress_callback_count",
            ),
            required_fields=(
                "final_status",
                "cancel_supported",
                "idle_detection_supported",
            ),
        ),
    )


def build_readiness_report(
    *,
    repo_root: Path,
    workloads: Sequence[WorkloadSpec],
    samples: int,
    timeout_seconds: float,
    sample_runner: SampleRunner = run_command_sample,
) -> dict[str, object]:
    """Run and summarize the deterministic DD-0 workload matrix."""

    if samples < 1:
        msg = "samples must be at least 1"
        raise ValueError(msg)
    return {
        "context": collect_context(repo_root),
        "settings": {
            "samples_per_workload": samples,
            "timeout_seconds": timeout_seconds,
            "network_access": "disabled by fixture design",
        },
        "workloads": [
            summarize_workload(
                workload,
                [sample_runner(workload, repo_root, timeout_seconds) for _ in range(samples)],
            )
            for workload in workloads
        ],
    }
