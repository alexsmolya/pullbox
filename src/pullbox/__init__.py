"""Pullbox — modern comic book management and acquisition platform."""

from datetime import UTC, datetime

__version__ = "0.9.9"

# Set once at process start; used by System > About for uptime calculation.
STARTED_AT: datetime = datetime.now(UTC)
