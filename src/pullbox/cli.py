"""Pullbox CLI — management commands for Docker and production environments.

Provides commands that can be run via ``docker exec`` when the web UI is
inaccessible (e.g., locked out, forgot password).

Usage::

    printf '%s\n' 'NewPass1!' | docker exec -i pullbox \
        python -m pullbox.cli reset-password --user admin --password-stdin
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.config import get_settings
from pullbox.core.password_policy import validate_password
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService


async def _reset_password(username: str, candidate_secret: str) -> None:
    """Validate password, update the user's hash, and invalidate all sessions."""
    violations = validate_password(candidate_secret)
    if violations:
        # These are static policy requirement strings; candidate_secret is never printed.
        # codeql[py/clear-text-logging-sensitive-data]
        print("Password does not meet requirements:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    engine = create_async_engine(settings.db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

            if not user:
                print(f"Error: user '{username}' not found.", file=sys.stderr)
                sys.exit(1)

            user.password_hash = AuthService.hash_password(candidate_secret)
            user.session_version += 1
            await session.commit()

            print(f"Password reset for user '{username}'.")
            print(
                f"Session version bumped to {user.session_version}"
                " — all existing sessions invalidated."
            )
    finally:
        await engine.dispose()


def _read_password(*, password_stdin: bool) -> str:
    """Read a password without exposing it in process arguments."""
    if password_stdin:
        secret = sys.stdin.readline().rstrip("\r\n")
        if not secret:
            print("Error: no password was provided on stdin.", file=sys.stderr)
            sys.exit(1)
        return secret

    secret = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if secret != confirmation:
        print("Error: passwords do not match.", file=sys.stderr)
        sys.exit(1)
    return secret


def build_parser() -> argparse.ArgumentParser:
    """Build the Pullbox management CLI parser."""
    parser = argparse.ArgumentParser(
        prog="pullbox",
        description="Pullbox management commands",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # reset-password
    rp = subparsers.add_parser(
        "reset-password",
        help="Reset a user's password (use when locked out of the web UI)",
    )
    rp.add_argument("--user", "-u", required=True, help="Username to reset")
    rp.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the new password from stdin instead of prompting",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()

    args = parser.parse_args()

    if args.command == "reset-password":
        candidate_secret = _read_password(password_stdin=args.password_stdin)
        asyncio.run(_reset_password(args.user, candidate_secret))


if __name__ == "__main__":
    main()
