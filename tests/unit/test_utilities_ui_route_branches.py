"""Direct branch coverage for split utilities UI route helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException

from pullbox.models.issue import Issue
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.ui import utilities_routes
from pullbox.utilities.models import JobState, JobType, UtilityJob

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class RecordingTemplates:
    """Tiny template recorder so route tests can assert context directly."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette/Jinja2 template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        self.calls.append((template_name, context))
        return SimpleNamespace(template_name=template_name, context=context, status_code=200)


def _request(*, headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, cookies={}, state=SimpleNamespace())


def _user() -> SimpleNamespace:
    return SimpleNamespace(username="admin")


async def _config_values(_session: object, keys: Sequence[str]) -> dict[str, str]:
    values = {
        "utility_trash_folder": "/comics/.trash",
        "utility_export_folder": "/exports",
        "comics_directory": "/comics",
        "series_folder_template": "{Series} ({Year})",
        "comic_file_template": "{Series} #{Issue:03d}",
        "annual_file_template": "{Series} Annual #{Issue:03d}",
        "non_standard_file_template": "{Series} {Type} {Volume:02d}",
        "single_non_standard_file_template": "{Series} {Type}",
        "replace_illegal_characters": "true",
        "colon_replacement": "dash",
    }
    return {key: values[key] for key in keys if key in values}


@pytest.fixture
def configured_utilities_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(utilities_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        utilities_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    monkeypatch.setattr(utilities_routes, "_load_system_config_values", _config_values)
    monkeypatch.setattr(
        utilities_routes,
        "_resolve_utility_browse_paths",
        lambda configs: {
            "trash_folder": configs.get("utility_trash_folder", "/comics/.trash"),
            "export_folder": "/exports",
        },
    )
    monkeypatch.setattr(
        utilities_routes,
        "_build_rename_templates",
        lambda configs: {"comic": configs.get("comic_file_template", "")},
    )
    return templates


async def _seed_utilities_rows(session: AsyncSession) -> None:
    root = LibraryRoot(name="Main", path="/comics", enabled=True)
    session.add(root)
    await session.flush()
    series = Series(title="Batman", sort_title="batman", library_root_id=root.id)
    session.add(series)
    await session.flush()
    issue = Issue(series_id=series.id, issue_number=1)
    session.add(issue)
    await session.flush()
    session.add(
        LibraryFile(
            issue_id=issue.id,
            library_root_id=root.id,
            file_path="/comics/Batman 001.cbz",
            file_name="Batman 001.cbz",
            file_size=123,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.HIGH,
        )
    )
    jobs = [
        UtilityJob(
            id="completed",
            job_type=JobType.EXPORT_LIBRARY,
            display_name="Export",
            state=JobState.COMPLETED,
            total_items=2,
            completed_items=2,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:01:00+00:00",
            created_by="admin",
        ),
        UtilityJob(
            id="partial",
            job_type=JobType.MASS_RENAME,
            display_name="Rename",
            state=JobState.COMPLETED,
            total_items=2,
            completed_items=1,
            failed_items=1,
            skipped_items=0,
            warning_count=1,
            error_message="NEEDS_ATTENTION: one file",
            created_at="bad-date",
            completed_at="bad-date",
            created_by="admin",
        ),
        UtilityJob(
            id="failed",
            job_type=JobType.INTEGRITY_CHECK,
            display_name="Integrity",
            state=JobState.FAILED,
            total_items=1,
            completed_items=0,
            failed_items=1,
            skipped_items=0,
            created_at="2026-01-01T00:02:00+00:00",
            completed_at="2026-01-01T00:03:00+00:00",
        ),
        UtilityJob(
            id="cancelled",
            job_type=JobType.FILE_CONVERT,
            display_name="Convert",
            state=JobState.CANCELLED,
            total_items=1,
            completed_items=0,
            failed_items=0,
            skipped_items=1,
            created_at="2026-01-01T00:04:00+00:00",
            completed_at=None,
        ),
        UtilityJob(
            id="rolled",
            job_type=JobType.DB_CHECK_CLEANUP,
            display_name="DB Check",
            state=JobState.ROLLED_BACK,
            total_items=1,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            created_at="2026-01-01T00:05:00+00:00",
            completed_at="2026-01-01T00:06:00+00:00",
        ),
        UtilityJob(
            id="running",
            job_type=JobType.LIBRARY_PERMISSIONS,
            display_name="Permissions",
            state=JobState.RUNNING,
            total_items=1,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            created_at="2026-01-01T00:07:00+00:00",
        ),
        UtilityJob(
            id="queued",
            job_type=JobType.MASS_CONVERT_PIPELINE,
            display_name="Mass Convert",
            state=JobState.QUEUED,
            total_items=1,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            created_at="2026-01-01T00:08:00+00:00",
        ),
        UtilityJob(
            id="paused",
            job_type=JobType.MASS_RENAME,
            display_name="Paused",
            state=JobState.PAUSED,
            total_items=1,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            created_at="2026-01-01T00:09:00+00:00",
        ),
        UtilityJob(
            id="rollback",
            job_type=JobType.ROLLBACK,
            display_name="Rollback",
            state=JobState.COMPLETED,
            parent_job_id="completed",
            total_items=1,
            completed_items=1,
            failed_items=0,
            skipped_items=0,
            created_at="2026-01-01T00:10:00+00:00",
            completed_at="2026-01-01T00:11:00+00:00",
        ),
    ]
    session.add_all(jobs)
    await session.flush()


@pytest.mark.asyncio
async def test_utilities_runtime_seams_and_helper_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(utilities_routes, "_get_templates", None)
    monkeypatch.setattr(utilities_routes, "_build_context", None)
    monkeypatch.setattr(utilities_routes, "_load_system_config_values", None)
    monkeypatch.setattr(utilities_routes, "_resolve_utility_browse_paths", None)
    monkeypatch.setattr(utilities_routes, "_build_rename_templates", None)

    with pytest.raises(RuntimeError, match="templates"):
        utilities_routes._templates()
    with pytest.raises(RuntimeError, match="context builder"):
        utilities_routes._ctx(_request())
    with pytest.raises(RuntimeError, match="config loading"):
        await utilities_routes._config_values(SimpleNamespace(), ["utility_trash_folder"])  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="browse path"):
        utilities_routes._browse_paths({})
    with pytest.raises(RuntimeError, match="rename template"):
        utilities_routes._rename_templates({})

    assert utilities_routes._normalize_utility_history_sort("job") == "job"
    assert utilities_routes._normalize_utility_history_sort("-items") == "-items"
    assert utilities_routes._normalize_utility_history_sort("nope") == "-completed_at"
    assert utilities_routes._normalize_utility_history_status("PARTIAL") == "partial"
    assert utilities_routes._normalize_utility_history_status("unknown") == ""
    assert utilities_routes._utility_history_status_label("weird", "ROLLING_BACK") == "Rolling Back"
    assert utilities_routes._utility_history_status_pill_class("weird") == "pill-neutral"
    assert utilities_routes._utility_history_timestamp_label(None) == ""
    assert utilities_routes._utility_history_timestamp_label("not-a-date") == "not-a-date"


@pytest.mark.asyncio
async def test_utility_history_and_queue_contexts(
    db_session: AsyncSession,
    configured_utilities_routes: RecordingTemplates,
) -> None:
    del configured_utilities_routes
    await _seed_utilities_rows(db_session)

    queue_jobs, stats = await utilities_routes.load_utility_queue_snapshot(db_session)
    assert stats == {"running": 1, "queued": 1, "paused": 1, "total_completed": 6}
    assert any(job["id"] == "running" for job in queue_jobs)

    partial = await utilities_routes.load_utility_history_context(
        db_session,
        status="partial",
        sort="status",
        requested_page=99,
    )
    assert partial["utility_history_status"] == "partial"
    assert partial["page"] == 1
    assert partial["history_jobs"][0]["history_status_key"] == "partial"  # type: ignore[index]

    completed = await utilities_routes.load_utility_history_context(
        db_session,
        status="completed",
        sort="-job",
        requested_page=1,
    )
    completed_ids = [job["id"] for job in completed["history_jobs"]]  # type: ignore[index]
    assert "completed" in completed_ids
    assert "partial" not in completed_ids

    failed = await utilities_routes.load_utility_history_context(
        db_session,
        status="failed",
        sort="items",
        requested_page=1,
    )
    assert failed["history_jobs"][0]["history_status_label"] == "Failed"  # type: ignore[index]

    cancelled = await utilities_routes.load_utility_history_context(
        db_session,
        status="cancelled",
        requested_page=1,
    )
    assert cancelled["history_jobs"][0]["history_status_key"] == "cancelled"  # type: ignore[index]

    rolled_back = await utilities_routes.load_utility_history_context(
        db_session,
        status="rolled_back",
        requested_page=1,
    )
    assert rolled_back["history_jobs"][0]["history_status_key"] == "rolled_back"  # type: ignore[index]


@pytest.mark.asyncio
async def test_utilities_page_and_tab_routes_select_expected_templates(
    db_session: AsyncSession,
    configured_utilities_routes: RecordingTemplates,
) -> None:
    await _seed_utilities_rows(db_session)

    full = await utilities_routes.utilities_page(
        _request(),
        _user(),
        db_session,
        tab="unknown",
    )
    assert full.template_name == "pages/utilities.html"
    assert full.context["tab"] == "utilities"

    queue = await utilities_routes.utilities_page(
        _request(headers={"HX-Request": "true"}),
        _user(),
        db_session,
        tab="queue",
    )
    assert queue.template_name == "partials/utilities_content_bundle.html"
    assert "initial_jobs" in queue.context

    history = await utilities_routes.utilities_page(
        _request(headers={"HX-Request": "true", "HX-Target": "utilities-history-section"}),
        _user(),
        db_session,
        tab="history",
        utility_history_status="partial",
        sort="-completed_at",
        page=1,
    )
    assert history.template_name == "partials/utilities_history_section_bundle.html"

    htmx = await utilities_routes.htmx_utilities_tab(
        _request(),
        "history",
        _user(),
        db_session,
        utility_history_status="completed",
        sort="job",
        page=1,
    )
    assert htmx.template_name == "partials/utilities_content_bundle.html"
    assert htmx.context["history_sort"] == "job"
    assert configured_utilities_routes.calls[-1][0] == "partials/utilities_content_bundle.html"


@pytest.mark.asyncio
async def test_utility_workflow_pages_render_contexts(
    db_session: AsyncSession,
    configured_utilities_routes: RecordingTemplates,
) -> None:
    await _seed_utilities_rows(db_session)

    converter = await utilities_routes.utilities_converter(_request(), _user(), db_session)
    assert converter.template_name == "pages/utilities_converter.html"
    assert converter.context["utility_trash_folder"] == "/comics/.trash"

    mass_convert = await utilities_routes.utilities_mass_convert(_request(), _user(), db_session)
    assert mass_convert.template_name == "pages/utilities_mass_convert.html"
    assert mass_convert.context["utility_trash_folder_browse_path"] == "/comics/.trash"

    mass_rename = await utilities_routes.utilities_mass_rename(_request(), _user(), db_session)
    assert mass_rename.template_name == "pages/utilities_mass_rename.html"
    assert mass_rename.context["rename_templates"] == {"comic": "{Series} #{Issue:03d}"}
    assert mass_rename.context["allowed_browse_roots"] == ["/comics"]

    integrity = await utilities_routes.utilities_integrity(_request(), _user(), db_session)
    assert integrity.template_name == "pages/utilities_integrity.html"

    db_check = await utilities_routes.utilities_db_check(_request(), _user(), db_session)
    assert db_check.template_name == "pages/utilities_db_check.html"
    assert db_check.context["db_check_default_root"] == "/comics"

    permissions = await utilities_routes.utilities_permissions(_request(), _user(), db_session)
    assert permissions.template_name == "pages/utilities_permissions.html"
    assert permissions.context["library_roots"][0]["path"] == "/comics"  # type: ignore[index]

    export = await utilities_routes.utilities_export(_request(), _user(), db_session)
    assert export.template_name == "pages/utilities_export.html"
    assert export.context["utility_export_folder"] == "/exports"
    assert export.context["export_record_counts"]["file"]["all"] == 1  # type: ignore[index]
    assert configured_utilities_routes.calls[-1][0] == "pages/utilities_export.html"


@pytest.mark.asyncio
async def test_utility_history_job_detail_route_handles_missing_and_success(
    db_session: AsyncSession,
    configured_utilities_routes: RecordingTemplates,
) -> None:
    await _seed_utilities_rows(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await utilities_routes.htmx_utility_history_job_detail(
            _request(),
            "missing",
            _user(),
            db_session,
        )
    assert exc_info.value.status_code == 404

    detail = await utilities_routes.htmx_utility_history_job_detail(
        _request(),
        "partial",
        _user(),
        db_session,
    )
    assert detail.template_name == "partials/utilities_history_job_detail.html"
    assert detail.context["detail_job"]["history_status_key"] == "partial"  # type: ignore[index]
    assert configured_utilities_routes.calls[-1][0] == "partials/utilities_history_job_detail.html"
