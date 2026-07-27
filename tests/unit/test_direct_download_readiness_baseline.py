from __future__ import annotations

from pathlib import Path

import pytest

from pullbox.performance.direct_download_baseline import (
    CommandSample,
    WorkloadSpec,
    build_readiness_report,
    default_workloads,
    extract_json_report,
    summarize_workload,
)


def test_extract_json_report_ignores_non_json_prefix() -> None:
    report = extract_json_report('diagnostic line\n{"elapsed_ms": 12, "ok": true}\n')

    assert report == {"elapsed_ms": 12, "ok": True}


def test_extract_json_report_rejects_output_without_an_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        extract_json_report("not a benchmark report")


def test_summarize_workload_records_percentiles_metrics_memory_and_failures() -> None:
    workload = WorkloadSpec(
        workload_id="manual_issue_search",
        description="Synthetic manual issue search",
        command=("scripts/example.py",),
        numeric_fields=("query_count",),
        required_fields=("final_status",),
    )
    samples = [
        CommandSample(
            report={
                "elapsed_ms": 10,
                "query_count": 4,
                "peak_rss_bytes": 100,
                "final_status": "completed",
            },
            wall_elapsed_ms=12,
        ),
        CommandSample(
            report={
                "elapsed_ms": 30,
                "query_count": 6,
                "peak_rss_bytes": 300,
                "final_status": "completed",
            },
            wall_elapsed_ms=32,
        ),
        CommandSample(report=None, wall_elapsed_ms=1, error="timed out"),
    ]

    summary = summarize_workload(workload, samples)

    assert summary["samples_requested"] == 3
    assert summary["samples_completed"] == 2
    assert summary["failure_count"] == 1
    assert summary["failures"] == ["timed out"]
    assert summary["timing_ms"] == {
        "samples": 2,
        "min": 10.0,
        "median": 20.0,
        "p95": 30.0,
        "max": 30.0,
    }
    assert summary["metrics"]["query_count"]["median"] == 5.0  # type: ignore[index]
    assert summary["peak_rss_bytes"]["max"] == 300.0  # type: ignore[index]


def test_summarize_workload_rejects_reports_missing_required_fields() -> None:
    workload = WorkloadSpec(
        workload_id="search",
        description="Search",
        command=("scripts/example.py",),
        required_fields=("final_status",),
    )

    summary = summarize_workload(
        workload,
        [CommandSample(report={"elapsed_ms": 1}, wall_elapsed_ms=2)],
    )

    assert summary["samples_completed"] == 0
    assert summary["failure_count"] == 1
    assert "final_status" in summary["failures"][0]  # type: ignore[index]


def test_default_workloads_cover_dd0_baseline_without_live_network_targets() -> None:
    workloads = default_workloads(profile="quick")

    assert {workload.workload_id for workload in workloads} == {
        "manual_issue_search",
        "automated_issue_search_core",
        "import_scan_and_match",
        "archive_post_processing",
        "download_progress_updates",
        "local_file_transfer",
    }
    commands = " ".join(part for workload in workloads for part in workload.command)
    assert "http://" not in commands
    assert "https://" not in commands


def test_build_readiness_report_uses_injected_sample_runner() -> None:
    workload = WorkloadSpec(
        workload_id="probe",
        description="Probe",
        command=("scripts/probe.py",),
        numeric_fields=("request_count",),
        required_fields=("final_status",),
    )
    calls: list[tuple[str, float]] = []

    def sample_runner(
        spec: WorkloadSpec,
        _repo_root: Path,
        timeout_seconds: float,
    ) -> CommandSample:
        calls.append((spec.workload_id, timeout_seconds))
        return CommandSample(
            report={
                "elapsed_ms": 4,
                "request_count": 2,
                "final_status": "completed",
            },
            wall_elapsed_ms=5,
        )

    report = build_readiness_report(
        repo_root=Path("/tmp/repo"),
        workloads=(workload,),
        samples=3,
        timeout_seconds=7,
        sample_runner=sample_runner,
    )

    assert calls == [("probe", 7), ("probe", 7), ("probe", 7)]
    assert report["settings"]["samples_per_workload"] == 3  # type: ignore[index]
    assert report["workloads"][0]["samples_completed"] == 3  # type: ignore[index]
