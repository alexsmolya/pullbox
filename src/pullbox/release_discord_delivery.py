"""Record Discord release deliveries so workflow retries never repost them."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def delivery_task(channel: str) -> str:
    """Return the stable GitHub Deployment task for a Discord channel."""
    if channel not in {"changelog", "announcements"}:
        raise ValueError(f"Unsupported Discord channel: {channel}")
    return f"pullbox-discord-{channel}"


def _request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request) as response:
        return json.load(response)


def reserve_delivery(
    *,
    api_url: str,
    repository: str,
    token: str,
    ref: str,
    run_url: str,
    version: str,
    channel: str,
) -> int | None:
    """Reserve a delivery, or return ``None`` after a prior successful post.

    Any incomplete prior delivery stays blocked for human review. This is safer
    than automatically retrying an operation whose Discord result is unknown.
    """
    task = delivery_task(channel)
    deployments_url = f"{api_url}/repos/{repository}/deployments?" + urlencode(
        {"environment": "pullbox-discord", "task": task, "per_page": 100}
    )
    for deployment in _request("GET", deployments_url, token):
        payload = deployment.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if payload.get("version") != version:
            continue
        statuses_url = (
            f"{api_url}/repos/{repository}/deployments/{deployment['id']}/statuses?per_page=1"
        )
        statuses = _request("GET", statuses_url, token)
        if statuses and statuses[0].get("state") == "success":
            return None
        message = f"Discord {channel} delivery for v{version} is already pending or failed"
        raise RuntimeError(f"{message}; review it before retrying.")

    deployment = _request(
        "POST",
        f"{api_url}/repos/{repository}/deployments",
        token,
        {
            "ref": ref,
            "task": task,
            "environment": "pullbox-discord",
            "description": f"Discord {channel} delivery for v{version}",
            "auto_merge": False,
            "required_contexts": [],
            "payload": {"version": version},
            "production_environment": False,
        },
    )
    record_delivery(
        api_url=api_url,
        repository=repository,
        token=token,
        deployment_id=deployment["id"],
        state="in_progress",
        run_url=run_url,
        description=f"Sending Discord {channel}",
    )
    return int(deployment["id"])


def record_delivery(
    *,
    api_url: str,
    repository: str,
    token: str,
    deployment_id: int,
    state: str,
    run_url: str,
    description: str,
) -> None:
    """Record the final state of a reserved Discord delivery."""
    _request(
        "POST",
        f"{api_url}/repos/{repository}/deployments/{deployment_id}/statuses",
        token,
        {
            "state": state,
            "environment": "pullbox-discord",
            "log_url": run_url,
            "description": description,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reserve or record a Discord release delivery.")
    parser.add_argument("action", choices=("reserve", "success"))
    parser.add_argument("--channel", required=True, choices=("changelog", "announcements"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--deployment-id", type=int)
    args = parser.parse_args(argv)

    token = os.environ["GITHUB_TOKEN"]
    api_url = os.environ["GITHUB_API_URL"]
    repository = os.environ["GITHUB_REPOSITORY"]
    run_url = (
        f"{os.environ['GITHUB_SERVER_URL']}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    )
    if args.action == "reserve":
        deployment_id = reserve_delivery(
            api_url=api_url,
            repository=repository,
            token=token,
            ref=os.environ["GITHUB_SHA"],
            run_url=run_url,
            version=args.version,
            channel=args.channel,
        )
        if deployment_id is None:
            print("skip=true")
        else:
            print(f"deployment_id={deployment_id}")
        return 0

    if args.deployment_id is None:
        parser.error("--deployment-id is required for success")
    record_delivery(
        api_url=api_url,
        repository=repository,
        token=token,
        deployment_id=args.deployment_id,
        state="success",
        run_url=run_url,
        description=f"Posted Discord {args.channel}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
