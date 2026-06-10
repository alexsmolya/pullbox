"""Publisher ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.series import Series


class Publisher(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "publishers"

    comicvine_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    logo_path: Mapped[str | None] = mapped_column(String(500))
    comicvine_url: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    series: Mapped[list[Series]] = relationship(back_populates="publisher")
