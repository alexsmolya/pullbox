"""Shared fixtures for utility tests — session factory, queue manager, stub executor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.utilities.base_executor import ItemResult, JobExecutor, ProcessedItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.fixture
def session_factory(async_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Provide an async session factory bound to the test engine."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


class StubExecutor(JobExecutor):
    """Test executor that completes all items successfully."""

    async def generate_items(self, job_config: dict[str, Any]) -> list[dict[str, Any]]:
        count = job_config.get("count", 3)
        return [
            {"file_path": f"/comics/file_{i}.cbr", "operation": "test_op"} for i in range(count)
        ]

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(
            item_id=item_data.get("id", ""),
            result=ItemResult.COMPLETED,
            before_state={"path": item_data.get("file_path", "")},
            after_state={"processed": True},
            duration_ms=5,
            log_entries=[("INFO", f"Processed {item_data.get('file_path', '')}", {})],
        )

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(
            item_id=item_data.get("id", ""),
            result=ItemResult.COMPLETED,
            log_entries=[("INFO", "Rolled back", {})],
        )
