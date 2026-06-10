"""Download post-processing runtime helper characterization tests."""

from __future__ import annotations

from types import SimpleNamespace

from pullbox.models.download import DownloadClientType
from pullbox.tasks.post_processing_progress import PostProcessingPhase, PostProcessingRunTrace


class _FakeLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def debug(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


class _FakeSummaryLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


def test_runtime_enter_phase_updates_trace_and_progress() -> None:
    """Phase entry should update trace, progress cache, and debug logging together."""
    from pullbox.tasks.download_post_processing_runtime import PostProcessingRuntime

    progress_calls: list[tuple[int, PostProcessingPhase]] = []
    download = SimpleNamespace(id=7, issue_id=11)
    trace = PostProcessingRunTrace(download_id=download.id)
    log = _FakeLog()
    runtime = PostProcessingRuntime(
        download=download,
        trace=trace,
        log=log,
        summary_logger=_FakeSummaryLogger(),
        set_phase=lambda download_id, phase: progress_calls.append((download_id, phase)),
    )

    runtime.enter_phase(PostProcessingPhase.VALIDATING_FILES)

    assert trace.current_phase == PostProcessingPhase.VALIDATING_FILES
    assert progress_calls == [(7, PostProcessingPhase.VALIDATING_FILES)]
    assert log.events == [
        (
            "post_processing_phase_entered",
            {
                "download_id": 7,
                "issue_id": 11,
                "phase": "validating_files",
                "phase_label": "Validating files",
            },
        )
    ]


def test_runtime_emit_summary_uses_trace_and_download_fields() -> None:
    """Summary emission should keep the existing payload shape centralized."""
    from pullbox.tasks.download_post_processing_runtime import PostProcessingRuntime

    download = SimpleNamespace(
        id=7,
        issue_id=11,
        download_client=DownloadClientType.SABNZBD,
        final_path="/library/final.cbz",
    )
    trace = PostProcessingRunTrace(download_id=download.id)
    trace.source_path = "/downloads/source.cbz"
    trace.final_path = "/library/trace-final.cbz"
    trace.file_size_bytes = 1234
    logger = _FakeSummaryLogger()
    runtime = PostProcessingRuntime(
        download=download,
        trace=trace,
        log=_FakeLog(),
        summary_logger=logger,
        set_phase=lambda download_id, phase: None,
    )

    runtime.emit_summary(outcome="success")

    assert logger.events[0][0] == "post_processing_lifecycle_summary"
    payload = logger.events[0][1]
    assert payload["download_id"] == 7
    assert payload["issue_id"] == 11
    assert payload["download_client"] == "sabnzbd"
    assert payload["outcome"] == "success"
    assert payload["source_path"] == "/downloads/source.cbz"
    assert payload["final_path"] == "/library/trace-final.cbz"
    assert payload["file_size_bytes"] == 1234
