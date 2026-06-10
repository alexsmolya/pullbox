"""Value types used by health checks and health result serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pullbox.models.health import HealthStatus


@dataclass
class CheckOutcome:
    """Result of a single health check, before persistence."""

    component: str
    check_name: str
    status: HealthStatus
    message: str
    subject_key: str | None = None
    subject_label: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    response_time_ms: float = 0.0
    actionable_guidance: str = ""
    sub_checks: tuple[SubCheckOutcome, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SubCheckOutcome:
    """Persistable sub-check for a component health run."""

    check_name: str
    name: str
    status: HealthStatus
    message: str
    subject_key: str | None = None
    subject_label: str | None = None
    response_time_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
