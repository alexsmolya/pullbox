"""Pullbox CLI — management commands for Docker and production environments.

Provides commands that can be run via ``docker exec`` when the web UI is
inaccessible (e.g., locked out, forgot password).

Usage::

    docker exec pullbox python -m pullbox.cli reset-password --user admin --password "NewPass1!"
"""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.config import get_settings
from pullbox.core.password_policy import validate_password
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService


async def _reset_password(username: str, new_password: str) -> None:
    """Validate password, update the user's hash, and invalidate all sessions."""
    violations = validate_password(new_password)
    if violations:
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

            user.password_hash = AuthService.hash_password(new_password)
            user.session_version += 1
            await session.commit()

            print(f"Password reset for user '{username}'.")
            print(
                f"Session version bumped to {user.session_version}"
                " — all existing sessions invalidated."
            )
    finally:
        await engine.dispose()


def main() -> None:
    """CLI entry point."""
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
    rp.add_argument("--password", "-p", required=True, help="New password")

    args = parser.parse_args()

    if args.command == "reset-password":
        asyncio.run(_reset_password(args.user, args.password))


if __name__ == "__main__":
    main()
