"""Guardrails for Alembic migration hygiene."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "alembic" / "versions"


def test_alembic_migrations_have_single_head() -> None:
    """The migration graph should not grow accidental branch heads."""
    config = Config(str(REPO_ROOT / "alembic" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1


def test_migration_files_define_upgrade_and_downgrade() -> None:
    """Every migration should be reversible unless explicitly revisited."""
    offenders: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        text = path.read_text()
        if "def upgrade(" not in text or "def downgrade(" not in text:
            offenders.append(path.name)

    assert offenders == []
