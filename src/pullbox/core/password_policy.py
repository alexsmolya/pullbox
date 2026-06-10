"""Password and username validation — enforce security policies on credentials."""

from __future__ import annotations

import re

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_PASSWORD_BYTES = 72
_MIN_USERNAME_LENGTH = 3
_MAX_USERNAME_LENGTH = 50

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
SPECIAL_CHARS = frozenset("!@#$%^&*()_+-=[]{}|;:'\",.<>?/`~")


def validate_password(password: str) -> list[str]:
    """Validate a password against the security policy.

    Returns a list of violation messages. An empty list means the
    password is valid.
    """
    violations: list[str] = []

    if len(password) < MIN_PASSWORD_LENGTH:
        violations.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        violations.append(f"Password must be at most {MAX_PASSWORD_LENGTH} characters long.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        violations.append(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes when encoded as UTF-8."
        )
    if not any(c.isupper() for c in password):
        violations.append("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        violations.append("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        violations.append("Password must contain at least one digit.")
    if not any(c in SPECIAL_CHARS for c in password):
        violations.append("Password must contain at least one special character.")

    return violations


def check_password_strength(password: str) -> str:
    """Rate password strength as 'weak', 'moderate', or 'strong'.

    Based on length and character-class diversity.
    """
    if validate_password(password):
        return "weak"

    diversity = sum(
        [
            any(c.isupper() for c in password),
            any(c.islower() for c in password),
            any(c.isdigit() for c in password),
            any(c in SPECIAL_CHARS for c in password),
        ]
    )

    if len(password) >= 16 and diversity == 4:
        return "strong"
    if len(password) >= 12 or diversity >= 3:
        return "moderate"
    return "weak"


def validate_username(username: str) -> list[str]:
    """Validate a username format.

    Returns a list of violation messages. An empty list means the
    username is valid.
    """
    violations: list[str] = []

    if len(username) < _MIN_USERNAME_LENGTH:
        violations.append(f"Username must be at least {_MIN_USERNAME_LENGTH} characters.")
    if len(username) > _MAX_USERNAME_LENGTH:
        violations.append(f"Username must be at most {_MAX_USERNAME_LENGTH} characters.")
    if not _USERNAME_RE.match(username):
        violations.append("Username may only contain letters, numbers, underscores, and hyphens.")

    return violations
