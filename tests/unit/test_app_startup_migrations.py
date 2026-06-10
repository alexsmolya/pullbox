from __future__ import annotations

from subprocess import CompletedProcess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from pullbox import app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_dev_auto_migrate_runs_alembic_upgrade_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alembic_dir = tmp_path / "alembic"
    alembic_dir.mkdir()
    alembic_ini = alembic_dir / "alembic.ini"
    alembic_ini.write_text("[alembic]\n", encoding="utf-8")
    monkeypatch.setenv("PULLBOX_DEV_AUTO_MIGRATE", "true")

    with (
        patch("pullbox.app._resolve_alembic_ini", return_value=alembic_ini),
        patch(
            "subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
        ) as run_mock,
    ):
        await app._run_dev_auto_migrations_if_enabled()

    run_mock.assert_called_once()
    command = run_mock.call_args.args[0]
    assert command[-4:] == ["-c", str(alembic_ini), "upgrade", "head"]
    assert "alembic" in command
    assert run_mock.call_args.kwargs["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_dev_auto_migrate_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PULLBOX_DEV_AUTO_MIGRATE", raising=False)

    with patch("subprocess.run") as run_mock:
        await app._run_dev_auto_migrations_if_enabled()

    run_mock.assert_not_called()
