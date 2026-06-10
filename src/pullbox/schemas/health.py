"""Health check request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.health import HealthStatus


class HealthComponentDetail(BaseModel):
    """Health status for a single component."""

    component: str = Field(description="Component name (e.g. 'database', 'comicvine')")
    status: HealthStatus
    message: str | None = None
    details: dict[str, Any] | None = Field(None, description="Sub-check breakdown details")
    response_time_ms: float | None = Field(None, description="Response time in milliseconds")
    last_checked: datetime | None = None
    actionable_guidance: str | None = None


class HealthOverview(BaseModel):
    """Overall system health summary."""

    status: HealthStatus = Field(description="Aggregate system health status")
    components: list[HealthComponentDetail] = Field(
        default_factory=list, description="Per-component health details"
    )
    checked_at: datetime = Field(description="When the health check was performed")


class HealthHistoryItem(BaseModel):
    """Single health check result from history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    component: str
    check_name: str
    subject_key: str | None = None
    subject_label: str | None = None
    status: HealthStatus
    message: str | None = None
    details: dict[str, Any] | None = None
    response_time_ms: float | None = None
    checked_at: datetime


class HealthSummary(BaseModel):
    """Counts by status level."""

    healthy: int = 0
    degraded: int = 0
    unhealthy: int = 0
    unknown: int = 0
    total_check_time_ms: float = 0.0


class HealthCheckResponse(BaseModel):
    """Full health report returned by GET /api/v1/health."""

    status: HealthStatus
    timestamp: datetime
    components: list[HealthComponentDetail] = Field(default_factory=list)
    summary: HealthSummary = Field(default_factory=HealthSummary)


class HealthComponentResponse(BaseModel):
    """Single component health detail with checks."""

    component: str
    status: HealthStatus
    checks: list[HealthComponentDetail] = Field(default_factory=list)


class HealthHistoryResponse(BaseModel):
    """Paginated list of health check history items."""

    items: list[HealthHistoryItem] = Field(default_factory=list)
    total: int = 0


class HealthIncidentItem(BaseModel):
    """Compact long-term non-healthy health span."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    component: str
    check_name: str
    subject_key: str | None = None
    subject_label: str | None = None
    status: HealthStatus
    message: str | None = None
    details: dict[str, Any] | None = None
    response_time_ms: float | None = None
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None = None


class HealthIncidentResponse(BaseModel):
    """Paginated list of compact health incidents."""

    items: list[HealthIncidentItem] = Field(default_factory=list)
    total: int = 0
