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
    token = os.environ.get("SIGSTORE_ID_TOKEN") or os.environ.get("CIRCLE_OIDC_TOKEN_V2", "")
    if not token:
        raise SystemExit("SIGSTORE_ID_TOKEN or CIRCLE_OIDC_TOKEN_V2 is required")

    payload = decode_payload(token)
    issuer = require_string(payload, "iss")
    project_id = require_string(payload, "oidc.circleci.com/project-id")
    pipeline_definition_id = require_string(payload, "oidc.circleci.com/pipeline-definition-id")
    vcs_origin = payload.get("oidc.circleci.com/vcs-origin", "")
    vcs_ref = payload.get("oidc.circleci.com/vcs-ref", "")
    certificate_identity = (
        "https://circleci.com/api/v2/projects/"
        f"{project_id}/pipeline-definitions/{pipeline_definition_id}"
    )

    values = {
        "COSIGN_CERTIFICATE_OIDC_ISSUER": issuer,
        "COSIGN_CERTIFICATE_IDENTITY": certificate_identity,
        "CIRCLECI_OIDC_PROJECT_ID": project_id,
        "CIRCLECI_OIDC_PIPELINE_DEFINITION_ID": pipeline_definition_id,
        "CIRCLECI_OIDC_VCS_ORIGIN": vcs_origin if isinstance(vcs_origin, str) else "",
        "CIRCLECI_OIDC_VCS_REF": vcs_ref if isinstance(vcs_ref, str) else "",
    }
    for name, value in values.items():
        print(f"export {name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
