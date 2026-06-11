"""Reset a user's password from the command line.

Use when locked out of the web UI. Validates password policy, updates the
hash, and invalidates all existing sessions for that user.

Local source-tree usage:
    PULLBOX_SECRET_KEY=test python scripts/reset_password.py <username> <new_password>

Production Docker usage:
    printf '%s\n' 'NewPass1!' | docker exec -i pullbox \
        python -m pullbox.cli reset-password --user admin --password-stdin
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the project root is on sys.path so pullbox is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.core.password_policy import validate_password
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService


async def reset_password(session: AsyncSession, username: str, new_password: str) -> User:
    """Validate *new_password*, update the user's hash, and bump session version.

    Returns the updated User on success.

    Raises:
        ValueError: If the password fails policy validation.
        LookupError: If no user with *username* exists.
    """
    violations = validate_password(new_password)
    if violations:
        raise ValueError(violations)

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        raise LookupError(username)

    user.password_hash = AuthService.hash_password(new_password)
    user.session_version += 1
    await session.flush()
    return user


async def main() -> None:
    """CLI entry point — parse args, connect to DB, reset password."""
    if len(sys.argv) != 3:
        print("Usage: python scripts/reset_password.py <username> <new_password>")
        sys.exit(1)

    username = sys.argv[1]
    new_password = sys.argv[2]

    settings = get_settings()
    engine = create_async_engine(settings.db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            try:
                user = await reset_password(session, username, new_password)
            except ValueError as exc:
                print("Password does not meet requirements:", file=sys.stderr)
                for v in exc.args[0]:
                    print(f"  - {v}", file=sys.stderr)
                sys.exit(1)
            except LookupError:
                print(f"Error: user '{username}' not found.", file=sys.stderr)
                sys.exit(1)

            await session.commit()
            print(f"Password reset for user '{username}'.")
            print(
                f"Session version bumped to {user.session_version}"
                " — all existing sessions invalidated."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
