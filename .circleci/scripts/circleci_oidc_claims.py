#!/usr/bin/env python3
"""Extract CircleCI OIDC claims needed for Cosign verification."""

from __future__ import annotations

import base64
import json
import os
import shlex


def decode_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) < 2:
        raise SystemExit("CIRCLE_OIDC_TOKEN_V2 is not a valid JWT")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
    data = json.loads(decoded.decode("utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("CIRCLE_OIDC_TOKEN_V2 payload was not a JSON object")
    return data


def require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"CIRCLE_OIDC_TOKEN_V2 is missing required claim: {key}")
    return value


def main() -> int:
    token = os.environ.get("CIRCLE_OIDC_TOKEN_V2", "")
    if not token:
        raise SystemExit("CIRCLE_OIDC_TOKEN_V2 is required")

    payload = decode_payload(token)
    issuer = require_string(payload, "iss")
    subject = require_string(payload, "sub")
    project_id = payload.get("oidc.circleci.com/project-id", "")
    vcs_origin = payload.get("oidc.circleci.com/vcs-origin", "")
    vcs_ref = payload.get("oidc.circleci.com/vcs-ref", "")

    values = {
        "COSIGN_CERTIFICATE_OIDC_ISSUER": issuer,
        "COSIGN_CERTIFICATE_IDENTITY": subject,
        "CIRCLECI_OIDC_PROJECT_ID": project_id if isinstance(project_id, str) else "",
        "CIRCLECI_OIDC_VCS_ORIGIN": vcs_origin if isinstance(vcs_origin, str) else "",
        "CIRCLECI_OIDC_VCS_REF": vcs_ref if isinstance(vcs_ref, str) else "",
    }
    for name, value in values.items():
        print(f"export {name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
