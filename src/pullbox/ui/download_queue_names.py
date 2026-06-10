"""Downloads queue display-name helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from pullbox.core.naming import (
    format_comic_file,
    issue_type_supports_volume,
    issue_type_uses_collection_template,
    normalize_issue_type_for_naming,
    resolve_collection_non_standard_file_template,
    resolve_single_non_standard_file_template,
)
from pullbox.models.config import SystemConfig
from pullbox.models.issue import Issue, IssueType, is_non_standard_issue_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.download import DownloadHistory


async def build_queue_names(
    session: AsyncSession,
    downloads: Sequence[DownloadHistory],
) -> dict[int, str]:
    """Build renamed display names for queue items."""
    cfg_result = await session.execute(
        select(SystemConfig).where(
            SystemConfig.key.in_(
                [
                    "comic_file_template",
                    "annual_file_template",
                    "non_standard_file_template",
                    "single_non_standard_file_template",
                    "preferred_format",
                ]
            )
        )
    )
    configs: dict[str, str] = {c.key: c.value for c in cfg_result.scalars().all()}

    templates_map: dict[str, str] = {
        "issue": configs.get("comic_file_template", "{Series} ({Year}) #{Issue:03d}"),
        "annual": configs.get("annual_file_template", "{Series} ({Year}) Annual #{Issue:03d}"),
    }
    collection_ns_template = resolve_collection_non_standard_file_template(
        configs.get("non_standard_file_template")
    )
    single_ns_template = resolve_single_non_standard_file_template(
        configs.get("single_non_standard_file_template")
    )
    preferred_ext = configs.get("preferred_format", "cbz")

    renamed: dict[int, str] = {}
    counted_series_ids = {
        issue.series_id
        for dl in downloads
        if (issue := dl.issue) is not None and issue.issue_type in {IssueType.TPB, IssueType.VOLUME}
    }
    series_collection_counts: dict[int, int] = {}
    if counted_series_ids:
        count_result = await session.execute(
            select(Issue.series_id, func.count())
            .where(
                Issue.series_id.in_(counted_series_ids),
                Issue.issue_type.in_([IssueType.TPB, IssueType.VOLUME]),
            )
            .group_by(Issue.series_id)
        )
        series_collection_counts = {
            int(series_id): int(count)
            for series_id, count in count_result.all()
            if series_id is not None
        }
    for dl in downloads:
        issue = dl.issue
        if not issue:
            continue
        series = issue.series
        if not series:
            continue

        it = issue.issue_type
        issue_type_val = it.value if isinstance(it, IssueType) else str(it)
        effective_issue_type = normalize_issue_type_for_naming(
            issue_type_val,
            collection_series_entry_count=series_collection_counts.get(issue.series_id),
        )
        if is_non_standard_issue_type(issue_type_val):
            template = (
                collection_ns_template
                if issue_type_uses_collection_template(effective_issue_type)
                else single_ns_template
            )
        else:
            template = templates_map.get(issue_type_val, collection_ns_template)
        volume_number: int | None = None
        if (
            issue_type_supports_volume(effective_issue_type)
            and float(issue.issue_number).is_integer()
        ):
            volume_number = int(issue.issue_number)

        full_name = format_comic_file(
            series=series.title,
            year=series.year_start,
            issue=issue.issue_number,
            volume=volume_number,
            issue_type=effective_issue_type,
            title=issue.title,
            template=template,
            extension=preferred_ext,
        )
        renamed[dl.id] = full_name.rsplit(".", 1)[0]
    return renamed
