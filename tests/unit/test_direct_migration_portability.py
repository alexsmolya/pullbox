from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.migration import MigrationContext
from alembic.operations import Operations

if TYPE_CHECKING:
    from types import ModuleType


def _postgresql_upgrade_sql(module_name: str) -> str:
    output = io.StringIO()
    context = MigrationContext.configure(
        url="postgresql://",
        opts={"as_sql": True, "output_buffer": output},
    )
    module = _load_migration(module_name)
    original_op = module.op
    try:
        module.op = Operations(context)
        module.upgrade()
    finally:
        module.op = original_op
    return output.getvalue()


def _load_migration(module_name: str) -> ModuleType:
    path = Path(__file__).parents[2] / "alembic" / "versions" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration {module_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manual_resolver_opt_in_uses_postgresql_boolean_default() -> None:
    sql = _postgresql_upgrade_sql("i4e5f6g70829_add_manual_torznab_resolver_opt_in")

    assert "resolver_enabled BOOLEAN DEFAULT false NOT NULL" in sql


def test_manager_availability_uses_postgresql_boolean_default() -> None:
    sql = _postgresql_upgrade_sql("j5f6g7h81930_add_indexer_manager_identity")

    assert "manager_available BOOLEAN DEFAULT true NOT NULL" in sql
