"""Static contracts for CircleCI workflow trigger policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CIRCLECI_CONFIG = REPO_ROOT / ".circleci" / "config.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _workflow_job_configs(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    job_configs: list[dict[str, Any]] = []
    jobs = workflow.get("jobs")
    assert isinstance(jobs, list)

    for entry in jobs:
        assert isinstance(entry, dict)
        assert len(entry) == 1
        _, config = next(iter(entry.items()))
        assert isinstance(config, dict)
        job_configs.append(config)

    return job_configs


def test_pr_workflow_ignores_merge_pushes_and_tags() -> None:
    """Expensive checks should run for PR branches, not protected-branch pushes."""
    data = _load_yaml(CIRCLECI_CONFIG)
    workflows = data.get("workflows")
    assert isinstance(workflows, dict)
    pr_workflow = workflows.get("pr-and-merge-checks")
    assert isinstance(pr_workflow, dict)

    for config in _workflow_job_configs(pr_workflow):
        filters = config.get("filters")
        assert isinstance(filters, dict)
        assert filters.get("branches") == {"ignore": ["main", "develop"]}
        assert filters.get("tags") == {"ignore": "/.*/"}


def test_weekly_clean_room_schedule_is_disabled() -> None:
    data = _load_yaml(CIRCLECI_CONFIG)
    jobs = data.get("jobs")
    workflows = data.get("workflows")
    assert isinstance(jobs, dict)
    assert isinstance(workflows, dict)

    assert "clean-room" not in jobs
    assert "weekly-clean-room" not in workflows
    assert all(
        "triggers" not in workflow for workflow in workflows.values() if isinstance(workflow, dict)
    )


def test_release_digest_extraction_avoids_circleci_heredoc_parsing() -> None:
    config_text = CIRCLECI_CONFIG.read_text(encoding="utf-8")

    assert "python3 -c '" in config_text
    assert "python3 - <<'PY'" not in config_text
    assert "python3 - \\<<'PY'" not in config_text
    assert "/tmp/image-metadata.json" in config_text
    assert "/tmp/pullbox-workspace/release-image-digest/digest.txt" in config_text
