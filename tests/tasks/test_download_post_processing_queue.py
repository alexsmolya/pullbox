"""Completed-download post-processing queue characterization tests."""

from __future__ import annotations

import asyncio


def test_post_processing_queue_module_exposes_process_completed_runtime() -> None:
    """The completed-download drain should live beside the task module."""
    from pullbox.tasks import download_post_processing_queue

    assert isinstance(download_post_processing_queue._process_completed_lock, asyncio.Lock)
    assert callable(download_post_processing_queue.process_completed)
