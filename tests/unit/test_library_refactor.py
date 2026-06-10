"""Unit tests for library architecture refactor — Task R-1.2.

Verifies that periodic scanning, batch matching, and scan-related API
endpoints have been removed while preserving read-only library features.
"""

from pullbox.services.library_service import LibraryService
from pullbox.services.matching_service import MatchingService


class TestLibraryServiceScanRemoval:
    """Verify scan-related methods are removed from LibraryService."""

    def test_no_scan_method(self) -> None:
        assert not hasattr(LibraryService, "scan")

    def test_no_incremental_scan_method(self) -> None:
        assert not hasattr(LibraryService, "incremental_scan")

    def test_no_manage_folders_method(self) -> None:
        assert not hasattr(LibraryService, "_manage_folders")

    def test_no_ensure_series_folders_method(self) -> None:
        assert not hasattr(LibraryService, "ensure_series_folders")

    def test_no_cleanup_empty_folders_method(self) -> None:
        assert not hasattr(LibraryService, "cleanup_empty_folders")

    def test_get_unmatched_still_exists(self) -> None:
        assert hasattr(LibraryService, "get_unmatched")

    def test_get_stats_still_exists(self) -> None:
        assert hasattr(LibraryService, "get_stats")


class TestMatchingServiceBatchRemoval:
    """Verify match_all_unmatched is removed, core methods preserved."""

    def test_no_match_all_unmatched(self) -> None:
        assert not hasattr(MatchingService, "match_all_unmatched")

    def test_match_file_still_exists(self) -> None:
        assert hasattr(MatchingService, "match_file")

    def test_manual_match_still_exists(self) -> None:
        assert hasattr(MatchingService, "manual_match")

    def test_unmatch_file_still_exists(self) -> None:
        assert hasattr(MatchingService, "unmatch_file")


class TestScanTaskRemoval:
    """Verify scan_library task is removed from the scheduler registry."""

    def test_no_scan_library_in_registry(self) -> None:
        import pullbox.tasks  # noqa: F401 — triggers @scheduled_task decorators
        from pullbox.core.scheduler import _task_registry

        task_ids = {t.task_id for t in _task_registry}
        assert "scan_library" not in task_ids

    def test_cleanup_history_still_registered(self) -> None:
        import pullbox.tasks  # noqa: F401 — triggers @scheduled_task decorators
        from pullbox.core.scheduler import _task_registry

        task_ids = {t.task_id for t in _task_registry}
        assert "cleanup_history" in task_ids


class TestScanEventRemoval:
    """Verify LibraryScanCompleted event is removed."""

    def test_no_library_scan_completed_event(self) -> None:
        import pullbox.core.events as events

        assert not hasattr(events, "LibraryScanCompleted")


class TestScanApiRemoval:
    """Verify scan-related API endpoints are removed."""

    def test_no_trigger_scan_endpoint(self) -> None:
        from pullbox.api.v1 import library

        assert not hasattr(library, "trigger_scan")

    def test_no_scan_status_endpoint(self) -> None:
        from pullbox.api.v1 import library

        assert not hasattr(library, "scan_status")

    def test_no_roots_crud_endpoints(self) -> None:
        from pullbox.api.v1 import library

        assert not hasattr(library, "add_root")
        assert not hasattr(library, "delete_root")

    def test_list_unmatched_still_exists(self) -> None:
        from pullbox.api.v1 import library

        assert hasattr(library, "list_unmatched")

    def test_manual_match_still_exists(self) -> None:
        from pullbox.api.v1 import library

        assert hasattr(library, "manual_match")

    def test_library_stats_still_exists(self) -> None:
        from pullbox.api.v1 import library

        assert hasattr(library, "library_stats")
