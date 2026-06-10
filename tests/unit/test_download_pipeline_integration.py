"""Tests for Task R-2.2 — download pipeline uses register_library_file().

Verifies that _run_post_processing delegates LibraryFile creation and
Issue status updates to register_library_file() rather than inline logic.
"""

from __future__ import annotations

import os

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-download-pipe")


class TestDownloadPipelineUsesRegisterLibraryFile:
    """The download post-processing calls register_library_file() for record creation."""

    def test_post_processing_imports_register(self) -> None:
        """_run_post_processing references register_library_file."""
        import inspect

        from pullbox.tasks.download_task import _run_post_processing

        source = inspect.getsource(_run_post_processing)
        assert "register_library_file" in source

    def test_post_processing_no_inline_library_file_creation(self) -> None:
        """_run_post_processing should NOT directly create LibraryFile instances.

        The old inline code had patterns like:
            lf = LibraryFile(file_path=..., file_name=..., ...)
            session.add(lf)
        These should be replaced by register_library_file().
        """
        import inspect

        from pullbox.tasks.download_task import _run_post_processing

        source = inspect.getsource(_run_post_processing)
        # Should not directly instantiate LibraryFile
        assert "LibraryFile(" not in source

    def test_post_processing_no_format_map(self) -> None:
        """The inline format_map dict should be gone — register_library_file handles it."""
        import inspect

        from pullbox.tasks.download_task import _run_post_processing

        source = inspect.getsource(_run_post_processing)
        assert "format_map" not in source
