"""Database utility helpers — SQL wildcard escaping and query safety."""

from __future__ import annotations


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in user input.

    Prevents users from injecting ``%`` and ``_`` wildcards to manipulate
    query results or cause performance issues.  Backslashes are escaped
    first to avoid double-escaping.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
