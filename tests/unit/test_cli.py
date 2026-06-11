"""Tests for Pullbox management CLI contracts."""

from __future__ import annotations

import io

import pytest

from pullbox import cli


def test_reset_password_parser_does_not_accept_cleartext_password_argument() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["reset-password", "--user", "admin", "--password-stdin"])

    assert args.password_stdin is True
    with pytest.raises(SystemExit):
        parser.parse_args(["reset-password", "--user", "admin", "--password", "Secret1!"])


def test_read_password_from_stdin_strips_line_ending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("NewPass1!\n"))

    assert cli._read_password(password_stdin=True) == "NewPass1!"


def test_read_password_prompts_and_confirms(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(["NewPass1!", "NewPass1!"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(prompts))

    assert cli._read_password(password_stdin=False) == "NewPass1!"


def test_read_password_rejects_prompt_confirmation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = iter(["NewPass1!", "Different1!"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(prompts))

    with pytest.raises(SystemExit):
        cli._read_password(password_stdin=False)
