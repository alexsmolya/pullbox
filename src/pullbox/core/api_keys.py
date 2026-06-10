"""API key helpers shared by auth schemas and services."""

from __future__ import annotations

import hashlib

API_KEY_PREFIX = "pb_k1_"
API_KEY_RANDOM_HEX_CHARS = 64
API_KEY_LENGTH = len(API_KEY_PREFIX) + API_KEY_RANDOM_HEX_CHARS
MAX_API_KEY_NAME_LENGTH = 100


def hash_api_key(raw_key: str) -> str:
    """Return the database hash for a raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def is_well_formed_api_key(raw_key: str) -> bool:
    """Return True when a key has the expected Pullbox API-key envelope."""
    return raw_key.startswith(API_KEY_PREFIX) and len(raw_key) == API_KEY_LENGTH


def normalize_api_key_name(name: str) -> str:
    """Trim and collapse whitespace in user-facing API key names."""
    normalized = " ".join(name.split())
    if not normalized:
        msg = "API key name must not be blank."
        raise ValueError(msg)
    if len(normalized) > MAX_API_KEY_NAME_LENGTH:
        msg = f"API key name must be at most {MAX_API_KEY_NAME_LENGTH} characters."
        raise ValueError(msg)
    return normalized
