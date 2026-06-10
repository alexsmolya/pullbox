from __future__ import annotations

from pullbox.config import PullboxSettings


def test_settings_ignore_unprefixed_dotenv_entries(tmp_path, monkeypatch) -> None:
    """Deployment/runtime .env files may include non-Pullbox keys like TZ."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PULLBOX_PORT", raising=False)
    monkeypatch.delenv("PULLBOX_SECRET_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "TZ=America/Los_Angeles\nPULLBOX_PORT=9999\nPULLBOX_SECRET_KEY=from-dotenv\n",
        encoding="utf-8",
    )

    settings = PullboxSettings()

    assert settings.port == 9999
    assert settings.secret_key == "from-dotenv"
