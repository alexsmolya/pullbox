"""Dashboard briefing, scorecard, watchlist, and exception assembly."""

from __future__ import annotations

from pullbox.services.dashboard_helpers import (
    client_reliability_interpretation,
    count_label,
    count_state,
    delta_from_reference,
    flow_through_interpretation,
    format_count_delta,
    format_percent_label,
    format_rate_delta,
    rate_state_from_percent,
    release_risk_interpretation,
    review_debt_interpretation,
    search_yield_is_drifting,
    storage_growth_label,
    storage_interpretation,
    storage_is_accelerating,
    storage_runway_label,
)
from pullbox.services.dashboard_types import (
    DashboardBriefing,
    DashboardExceptionItem,
    DashboardLivePulse,
    DashboardPriority,
    DashboardScorecard,
    DashboardSnapshot,
    DashboardWatchItem,
)


class DashboardPresentationBuilder:
    """Build user-facing dashboard presentation objects from a metric snapshot."""

    def build_briefing(
        self,
        snapshot: DashboardSnapshot,
        priorities: list[DashboardPriority],
    ) -> DashboardBriefing:
        top_score = priorities[0].score if priorities else 0
        if top_score >= 60:
            state = "critical"
            state_label = "Critical"
            headline = "A few problems are lining up. Start with these."
            summary = (
                "The queues can recover, but they need a little help before the next wave hits."
            )
        elif top_score >= 40:
            state = "watch"
            state_label = "Watch"
            headline = "A few things are drifting. Worth a look before they pile up."
            summary = "Nothing is on fire yet, but the next detour is already obvious."
        else:
            state = "healthy"
            state_label = "Healthy"
            headline = "Nothing looks off right now."
            summary = (
                "Automation is keeping up. Keep an eye on the next few releases and let it run."
            )

        visible_priorities = tuple(priority for priority in priorities[:3] if priority.score >= 40)
        return DashboardBriefing(
            state=state,
            state_label=state_label,
            headline=headline,
            summary=summary,
            priorities=visible_priorities,
        )

    def build_scorecards(self, snapshot: DashboardSnapshot) -> tuple[DashboardScorecard, ...]:
        flow_state = rate_state_from_percent(snapshot.downloads.flow_through_rate)
        review_state = count_state(snapshot.review_debt.total, watch=1, critical=10)
        release_state = count_state(snapshot.release_risk.next_72h_count, watch=1, critical=4)
        client_state = rate_state_from_percent(snapshot.client_reliability.rate)
        storage_state = snapshot.storage.state

        return (
            DashboardScorecard(
                key="flow-through",
                title="Flow-through Rate",
                value_label=format_percent_label(snapshot.downloads.flow_through_rate),
                delta_label=format_rate_delta(
                    snapshot.downloads.flow_through_rate,
                    snapshot.downloads.previous_flow_through_rate,
                ),
                state=flow_state,
                interpretation=flow_through_interpretation(snapshot.downloads.flow_through_rate),
                cta_label="Open downloads",
                cta_href="/downloads?tab=history",
            ),
            DashboardScorecard(
                key="review-debt",
                title="Review Debt",
                value_label=count_label(snapshot.review_debt.total, singular="item"),
                delta_label=format_count_delta(
                    snapshot.review_debt.total,
                    snapshot.review_debt.reference_total,
                ),
                state=review_state,
                interpretation=review_debt_interpretation(snapshot.review_debt),
                cta_label="Open intervention",
                cta_href="/intervention",
            ),
            DashboardScorecard(
                key="release-risk",
                title="Release Risk",
                value_label=count_label(
                    snapshot.release_risk.next_72h_count,
                    singular="issue",
                ),
                delta_label=format_count_delta(
                    snapshot.release_risk.next_72h_count,
                    snapshot.release_risk.reference_count,
                ),
                state=release_state,
                interpretation=release_risk_interpretation(snapshot.release_risk),
                cta_label="Open pull list",
                cta_href="/pull-list",
            ),
            DashboardScorecard(
                key="client-reliability",
                title="Client Reliability",
                value_label=format_percent_label(snapshot.client_reliability.rate),
                delta_label=format_rate_delta(
                    snapshot.client_reliability.rate,
                    snapshot.client_reliability.previous_rate,
                ),
                state=client_state,
                interpretation=client_reliability_interpretation(snapshot.client_reliability),
                cta_label="Open downloads",
                cta_href="/downloads?tab=history",
            ),
            DashboardScorecard(
                key="storage-runway",
                title="Storage Runway",
                value_label=storage_runway_label(snapshot.storage),
                delta_label=storage_growth_label(snapshot.storage),
                state=storage_state,
                interpretation=storage_interpretation(snapshot.storage),
                cta_label="Open library",
                cta_href="/library",
            ),
        )

    def build_watch_items(self, snapshot: DashboardSnapshot) -> tuple[DashboardWatchItem, ...]:
        items: list[DashboardWatchItem] = []

        if snapshot.release_risk.next_7d_count > snapshot.release_risk.next_72h_count:
            items.append(
                DashboardWatchItem(
                    key="release-watch",
                    title="More releases are lining up after the next 72 hours.",
                    detail=(
                        f"{snapshot.release_risk.next_7d_count} issues are due in the next "
                        "week and still need coverage."
                    ),
                    trend_label="Next 7 days",
                    state="watch",
                    cta_label="Open pull list",
                    cta_href="/pull-list",
                )
            )

        review_delta = delta_from_reference(
            snapshot.review_debt.total,
            snapshot.review_debt.reference_total,
        )
        if review_delta is not None and review_delta > 0:
            items.append(
                DashboardWatchItem(
                    key="review-growth",
                    title="Manual review debt is climbing.",
                    detail=(
                        f"The queue is up by {review_delta} compared with the same point last week."
                    ),
                    trend_label="Backlog growth",
                    state="watch" if review_delta < 8 else "critical",
                    cta_label="Open intervention",
                    cta_href="/intervention",
                )
            )

        if snapshot.failure_clusters:
            cluster = snapshot.failure_clusters[0]
            items.append(
                DashboardWatchItem(
                    key="client-cluster",
                    title=cluster.title,
                    detail=cluster.detail,
                    trend_label=f"{cluster.count} repeats",
                    state=cluster.state,
                    cta_label=cluster.cta_label,
                    cta_href=cluster.cta_href,
                )
            )

        if storage_is_accelerating(snapshot.storage):
            items.append(
                DashboardWatchItem(
                    key="storage-acceleration",
                    title="Storage growth picked up this week.",
                    detail="Disk usage is climbing faster than the last baseline we have on file.",
                    trend_label="Growth acceleration",
                    state="watch",
                    cta_label="Open library",
                    cta_href="/library",
                )
            )

        if (
            snapshot.import_failures.total > 0
            and snapshot.import_failures.total > snapshot.import_failures.previous_total
        ):
            items.append(
                DashboardWatchItem(
                    key="import-spike",
                    title="Import failures are running hotter than last week.",
                    detail=f"{snapshot.import_failures.total} failures landed in the last 7 days.",
                    trend_label="Import spike",
                    state="watch" if snapshot.import_failures.total < 6 else "critical",
                    cta_label="Open import history",
                    cta_href="/import?tab=history",
                )
            )

        if search_yield_is_drifting(snapshot.search_yield):
            items.append(
                DashboardWatchItem(
                    key="search-drift",
                    title="Search yield dropped below the recent baseline.",
                    detail=(
                        "Searches are still running, but fewer of them are ending in usable grabs."
                    ),
                    trend_label="Search drift",
                    state="watch",
                    cta_label="Open search history",
                    cta_href="/search-history",
                )
            )

        if not items:
            items.append(
                DashboardWatchItem(
                    key="quiet-watchlist",
                    title="No drift worth chasing right now.",
                    detail="The next seven days look steady from here.",
                    trend_label="Quiet horizon",
                    state="healthy",
                    cta_label="Open health",
                    cta_href="/health",
                )
            )

        return tuple(items[:6])

    def build_exceptions(self, snapshot: DashboardSnapshot) -> tuple[DashboardExceptionItem, ...]:
        items: list[DashboardExceptionItem] = []

        for cluster in snapshot.failure_clusters:
            items.append(
                DashboardExceptionItem(
                    key=cluster.key,
                    title=cluster.title,
                    detail=cluster.detail,
                    badge_label=f"{cluster.count} repeats",
                    state=cluster.state,
                    cta_label=cluster.cta_label,
                    cta_href=cluster.cta_href,
                )
            )

        for cluster in snapshot.unmatched_clusters:
            items.append(
                DashboardExceptionItem(
                    key=cluster.key,
                    title=cluster.title,
                    detail=cluster.detail,
                    badge_label=f"{cluster.count} files",
                    state=cluster.state,
                    cta_label=cluster.cta_label,
                    cta_href=cluster.cta_href,
                )
            )

        if snapshot.health.problem_count > 0:
            items.append(
                DashboardExceptionItem(
                    key="health-problems",
                    title="Health checks are reporting repeat trouble.",
                    detail=(
                        ", ".join(snapshot.health.component_labels)
                        or "One or more components are degraded."
                    ),
                    badge_label=count_label(
                        snapshot.health.problem_count,
                        singular="alert",
                    ),
                    state="critical" if snapshot.health.unhealthy_count else "watch",
                    cta_label="Open health",
                    cta_href="/health",
                )
            )

        if snapshot.import_failures.total > 0:
            items.append(
                DashboardExceptionItem(
                    key="import-failures",
                    title="Recent import runs left cleanup behind.",
                    detail=(
                        f"{snapshot.import_failures.failed_jobs} failed jobs and "
                        f"{snapshot.import_failures.failed_files} failed file actions landed "
                        "this week."
                    ),
                    badge_label=f"{snapshot.import_failures.total} failures",
                    state="watch" if snapshot.import_failures.total < 6 else "critical",
                    cta_label="Open import history",
                    cta_href="/import?tab=history",
                )
            )

        if not items:
            items.append(
                DashboardExceptionItem(
                    key="quiet-exceptions",
                    title="No repeat failures are clustering right now.",
                    detail="The obvious anomalies are quiet.",
                    badge_label="All clear",
                    state="healthy",
                    cta_label="Open downloads",
                    cta_href="/downloads?tab=history",
                )
            )

        return tuple(items[:6])

    def build_live_pulse(self, snapshot: DashboardSnapshot) -> DashboardLivePulse:
        return DashboardLivePulse(
            active_downloads=snapshot.downloads.active_count,
            pending_decisions=snapshot.review_debt.total,
            next_72h_risk=snapshot.release_risk.next_72h_count,
            health_alerts=snapshot.health.problem_count,
        )
