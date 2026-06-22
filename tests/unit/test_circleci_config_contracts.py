"""Static contracts for CircleCI workflow trigger policy."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CIRCLECI_CONFIG = REPO_ROOT / ".circleci" / "config.yml"
CIRCLECI_OIDC_SCRIPT = REPO_ROOT / ".circleci" / "scripts" / "circleci_oidc_claims.py"
CIRCLECI_RELEASE_SYNC_SCRIPT = REPO_ROOT / ".circleci" / "scripts" / "release_sync_check.py"
CIRCLECI_FULL_CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "circleci-full-ci.yml"


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


def _workflow_job_names(workflow: dict[str, Any]) -> list[str]:
    job_names: list[str] = []
    jobs = workflow.get("jobs")
    assert isinstance(jobs, list)

    for entry in jobs:
        assert isinstance(entry, dict)
        assert len(entry) == 1
        job_key, config = next(iter(entry.items()))
        assert isinstance(config, dict)
        configured_name = config.get("name")
        job_names.append(configured_name if isinstance(configured_name, str) else job_key)

    return job_names


def test_pr_workflow_ignores_merge_pushes_and_tags() -> None:
    """PR checks should run for PR branches, not protected-branch pushes."""
    data = _load_yaml(CIRCLECI_CONFIG)
    workflows = data.get("workflows")
    assert isinstance(workflows, dict)

    for workflow_name in ("pr-preflight-checks", "pr-and-merge-checks"):
        pr_workflow = workflows.get(workflow_name)
        assert isinstance(pr_workflow, dict)

        for config in _workflow_job_configs(pr_workflow):
            filters = config.get("filters")
            assert isinstance(filters, dict)
            assert filters.get("branches") == {"ignore": ["main", "develop"]}
            assert filters.get("tags") == {"ignore": "/.*/"}


def test_pr_full_ci_is_explicitly_gated_after_preflight() -> None:
    """Default PR pushes should stay cheap until maintainers opt in to full CI."""
    data = _load_yaml(CIRCLECI_CONFIG)
    parameters = data.get("parameters")
    workflows = data.get("workflows")
    assert isinstance(parameters, dict)
    assert isinstance(workflows, dict)

    run_preflight = parameters.get("run_pr_preflight")
    run_full_ci = parameters.get("run_full_ci")
    assert run_preflight == {"type": "boolean", "default": True}
    assert run_full_ci == {"type": "boolean", "default": False}

    preflight = workflows.get("pr-preflight-checks")
    full_ci = workflows.get("pr-and-merge-checks")
    assert isinstance(preflight, dict)
    assert isinstance(full_ci, dict)
    assert preflight.get("when") == "<< pipeline.parameters.run_pr_preflight >>"
    assert full_ci.get("when") == "<< pipeline.parameters.run_full_ci >>"

    preflight_jobs = _workflow_job_names(preflight)
    full_ci_jobs = _workflow_job_names(full_ci)

    assert preflight_jobs == ["release-sync-check", "pr-preflight"]
    assert {"test-python-3.12", "test-python-3.13", "test-python-3.14"}.isdisjoint(preflight_jobs)
    assert {"accessibility", "e2e-chromium", "e2e-firefox", "docker-validate"}.isdisjoint(
        preflight_jobs
    )
    assert {"ci-required", "security-required", "workflow-hygiene-required"} <= set(full_ci_jobs)


def test_ci_full_label_bridge_dispatches_circleci_without_privileged_pr_target() -> None:
    """The GitHub bridge should only dispatch full CircleCI for explicit PR opt-in."""
    data = _load_yaml(CIRCLECI_FULL_CI_WORKFLOW)
    workflow_text = CIRCLECI_FULL_CI_WORKFLOW.read_text(encoding="utf-8")

    triggers = data.get(True, data.get("on"))
    assert isinstance(triggers, dict)
    pull_request = triggers.get("pull_request")
    assert isinstance(pull_request, dict)
    assert set(pull_request.get("types", [])) == {
        "labeled",
        "synchronize",
        "reopened",
        "ready_for_review",
    }

    assert "pull_request_target" not in workflow_text
    assert "contains(github.event.pull_request.labels.*.name, 'ci:full')" in workflow_text
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow_text
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in workflow_text
    assert "!startsWith(github.event.pull_request.head.ref, 'dependabot/')" in workflow_text
    assert "CIRCLECI_TOKEN repository secret is required" in workflow_text
    assert "run_pr_preflight: false" in workflow_text
    assert "run_full_ci: true" in workflow_text


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


def test_release_sync_check_accepts_pipeline_pr_context(monkeypatch: Any) -> None:
    """API-triggered full-CI pipelines should still be recognized as PR pipelines."""
    spec = importlib.util.spec_from_file_location(
        "circleci_release_sync_check", CIRCLECI_RELEASE_SYNC_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.delenv("CIRCLE_PULL_REQUEST", raising=False)
    monkeypatch.setenv("PULLBOX_PR_NUMBER", "48")
    monkeypatch.setenv("PULLBOX_BASE_BRANCH", "main")

    assert module._pull_request_number() == "48"
    assert module._pull_request_base_branch("pullboxapp/pullbox") == "main"


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
