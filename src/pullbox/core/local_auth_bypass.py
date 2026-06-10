"""Shared helpers for trusted local-address authentication bypass."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from pullbox.core.config_resolver import get_application_secret, load_system_config_values
from pullbox.models.user import User

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LocalAuthBypassPolicy:
    """Resolved local-auth-bypass settings."""

    enabled: bool
    addresses: str
    username: str


@dataclass(frozen=True)
class LocalAuthBypassResolution:
    """Outcome of evaluating a request against the local bypass policy."""

    enabled: bool
    client_ip: str
    user_id: int | None
    username: str | None
    csrf_token: str | None
    failure_reason: str | None


def normalize_local_bypass_addresses(raw: str) -> str:
    """Validate and canonicalize a comma-separated list of IP/CIDR entries."""
    normalized: list[str] = []
    for entry in raw.split(","):
        value = entry.strip()
        if not value:
            continue
        try:
            if "/" in value:
                normalized.append(str(ipaddress.ip_network(value, strict=False)))
            else:
                normalized.append(str(ipaddress.ip_address(value)))
        except ValueError as exc:
            raise ValueError(f"Invalid local bypass address or CIDR: {value}") from exc
    return ", ".join(normalized)


def is_local_address(client_ip: str, local_addresses: str) -> bool:
    """Return True when client_ip matches any configured IP or CIDR range."""
    if not local_addresses.strip():
        return False

    try:
        client = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for entry in local_addresses.split(","):
        value = entry.strip()
        if not value:
            continue
        try:
            if "/" in value:
                network = ipaddress.ip_network(value, strict=False)
                if client in network:
                    return True
            elif client == ipaddress.ip_address(value):
                return True
        except ValueError:
            continue

    return False


def resolve_client_ip(request: Request, trusted_proxies: str) -> str:
    """Resolve the effective client IP, accounting for explicitly trusted proxies."""
    raw_ip = request.client.host if request.client else "unknown"

    if not trusted_proxies.strip():
        if request.headers.get("x-forwarded-for"):
            logger.warning(
                "x_forwarded_for_present_but_no_trusted_proxies",
                raw_ip=raw_ip,
            )
        return raw_ip

    trusted_set = {value.strip() for value in trusted_proxies.split(",") if value.strip()}
    if raw_ip not in trusted_set:
        logger.debug("client_ip_resolved", raw=raw_ip, resolved=raw_ip)
        return raw_ip

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        resolved = x_real_ip.strip()
        logger.debug("client_ip_resolved", raw=raw_ip, resolved=resolved)
        return resolved

    xff = request.headers.get("x-forwarded-for")
    if xff:
        resolved = xff.split(",")[-1].strip()
        logger.debug("client_ip_resolved", raw=raw_ip, resolved=resolved)
        return resolved

    logger.debug("client_ip_resolved", raw=raw_ip, resolved=raw_ip)
    return raw_ip


def build_local_bypass_csrf_token(client_ip: str, username: str) -> str:
    """Derive a stable CSRF token for trusted-IP bypass requests."""
    payload = f"{client_ip}|{username}".encode()
    secret = get_application_secret().encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def local_bypass_policy_from_mapping(values: dict[str, str] | Any) -> LocalAuthBypassPolicy:
    """Build a LocalAuthBypassPolicy from a config mapping."""
    getter = values.get if hasattr(values, "get") else None
    if getter is None:
        return LocalAuthBypassPolicy(enabled=False, addresses="", username="")
    return LocalAuthBypassPolicy(
        enabled=str(getter("local_auth_bypass_enabled", "false")).lower() == "true",
        addresses=str(getter("local_auth_bypass_addresses", "") or ""),
        username=str(getter("local_auth_bypass_username", "") or "").strip(),
    )


async def load_local_auth_bypass_policy(session: AsyncSession) -> LocalAuthBypassPolicy:
    """Load the local bypass settings from system config."""
    try:
        values = await load_system_config_values(
            session,
            (
                "local_auth_bypass_enabled",
                "local_auth_bypass_addresses",
                "local_auth_bypass_username",
            ),
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "local_auth_bypass_policy_unavailable",
            error=str(exc),
        )
        return LocalAuthBypassPolicy(enabled=False, addresses="", username="")
    return local_bypass_policy_from_mapping(values)


async def resolve_local_bypass_user(
    session: AsyncSession,
    configured_username: str,
) -> tuple[User | None, str | None]:
    """Resolve which active user trusted-IP bypass should impersonate."""
    username = configured_username.strip()
    if username:
        result = await session.execute(
            select(User).where(User.username == username, User.is_active.is_(True)).limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None, "configured_user_missing"
        return user, None

    result = await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.id.asc()).limit(2)
    )
    users = list(result.scalars().all())
    if len(users) == 1:
        return users[0], None
    if len(users) == 0:
        return None, "no_active_users"
    return None, "multiple_active_users"


async def resolve_local_auth_bypass(
    request: Request,
    session: AsyncSession,
    trusted_proxies: str,
    *,
    policy: LocalAuthBypassPolicy | None = None,
) -> LocalAuthBypassResolution:
    """Resolve whether the request qualifies for trusted-IP bypass."""
    effective_policy = policy or await load_local_auth_bypass_policy(session)
    if not effective_policy.enabled or not effective_policy.addresses.strip():
        return LocalAuthBypassResolution(
            enabled=effective_policy.enabled,
            client_ip="",
            user_id=None,
            username=None,
            csrf_token=None,
            failure_reason="disabled_or_unconfigured",
        )

    client_ip = resolve_client_ip(request, trusted_proxies)
    if not client_ip or not is_local_address(client_ip, effective_policy.addresses):
        return LocalAuthBypassResolution(
            enabled=effective_policy.enabled,
            client_ip=client_ip,
            user_id=None,
            username=None,
            csrf_token=None,
            failure_reason="ip_not_allowed",
        )

    user, failure_reason = await resolve_local_bypass_user(session, effective_policy.username)
    if user is None:
        return LocalAuthBypassResolution(
            enabled=effective_policy.enabled,
            client_ip=client_ip,
            user_id=None,
            username=effective_policy.username or None,
            csrf_token=None,
            failure_reason=failure_reason,
        )

    return LocalAuthBypassResolution(
        enabled=effective_policy.enabled,
        client_ip=client_ip,
        user_id=user.id,
        username=user.username,
        csrf_token=build_local_bypass_csrf_token(client_ip, user.username),
        failure_reason=None,
    )
