"""Static contracts for CircleCI workflow trigger policy."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CIRCLECI_CONFIG = REPO_ROOT / ".circleci" / "config.yml"
CIRCLECI_OIDC_SCRIPT = REPO_ROOT / ".circleci" / "scripts" / "circleci_oidc_claims.py"


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


def test_release_signing_uses_sigstore_audience_oidc_token() -> None:
    config_text = CIRCLECI_CONFIG.read_text(encoding="utf-8")

    assert 'circleci run oidc get --claims \'{"aud": "sigstore"}\'' in config_text
    assert "export SIGSTORE_ID_TOKEN" in config_text
    assert 'cosign sign --yes --identity-token "${SIGSTORE_ID_TOKEN}"' in config_text
    assert 'cosign sign --yes --identity-token "${CIRCLE_OIDC_TOKEN_V2}"' not in config_text


def test_circleci_oidc_claims_emit_fulcio_certificate_identity(
    monkeypatch: Any, capsys: Any
) -> None:
    payload = {
        "iss": "https://oidc.circleci.com/org/org-123",
        "oidc.circleci.com/project-id": "project-456",
        "oidc.circleci.com/pipeline-definition-id": "definition-789",
        "oidc.circleci.com/vcs-origin": "https://github.com/pullboxapp/pullbox",
        "oidc.circleci.com/vcs-ref": "refs/tags/v0.9.11-rc3",
    }
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    token = f"header.{encoded_payload.rstrip('=')}.signature"
    spec = importlib.util.spec_from_file_location("circleci_oidc_claims", CIRCLECI_OIDC_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setenv("SIGSTORE_ID_TOKEN", token)

    assert module.main() == 0
    output = capsys.readouterr().out

    assert "export COSIGN_CERTIFICATE_OIDC_ISSUER=https://oidc.circleci.com/org/org-123" in output
    assert (
        "export COSIGN_CERTIFICATE_IDENTITY="
        "https://circleci.com/api/v2/projects/project-456/"
        "pipeline-definitions/definition-789"
    ) in output
    assert "export CIRCLECI_OIDC_PIPELINE_DEFINITION_ID=definition-789" in output
