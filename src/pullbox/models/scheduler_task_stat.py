"""Persisted scheduler task execution stats."""

from datetime import datetime

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, TimestampMixin, UTCDateTime


class ScheduledTaskStat(TimestampMixin, Base):
    """Last-known execution state for a scheduler task."""

    __tablename__ = "scheduled_task_stats"

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_execution: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_missed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    missed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_overlap_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    overlap_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_exclusive_block_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    exclusive_block_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
