# Pullbox CircleCI Migration

This folder moves Pullbox CI/CD into CircleCI while preserving the existing
quality, security, workflow hygiene, Docker validation, release publish, image
signing, and GitHub Release gates.

## Files

- `config.yml` - CircleCI 2.1 config covering CI, security, workflow hygiene,
  Docker validation, Docker release, image signing, and GitHub Release creation.
- `scripts/release_sync_check.py` - conservative release-sync fast-path detector.
- `scripts/docker_validate_gate.py` - Docker-sensitive path and trust detector.
- `scripts/circleci_oidc_claims.py` - extracts CircleCI OIDC issuer and subject
  for Cosign signature verification.
- `scripts/github_release.py` - GitHub Release create/update helper.

## Speed Optimizations Included

- Python 3.12, 3.13, and 3.14 run as separate workflow jobs.
- Each Python test job uses CircleCI `parallelism` plus timing-based splitting.
- Coverage is collected per shard and combined per Python version.
- E2E tests use CircleCI `parallelism` plus timing-based file splitting.
- JUnit results are stored with `store_test_results` to feed timing data and
  enable CircleCI rerun-failed-tests behavior.
- Pip, venv, npm, and Playwright browser caches are included.
- Docker Validate and Docker Release build/push jobs use Docker Layer Caching.
- Heavy jobs use larger resource classes by default.
- Docker publish remains tag/manual only.

## Trigger Policy

- Open pull requests run the cheap `pr-preflight-checks` workflow by default.
- Full PR CI/security/workflow-hygiene checks run only when a maintainer opts in
  with the `ci:full` label. The GitHub `CircleCI Full CI Trigger` workflow
  dispatches CircleCI with `run_full_ci=true` for same-repository PRs carrying
  that label.
- Pushes to PR branches with `ci:full` rerun the full gate. Remove the label
  while iterating if the PR should return to preflight-only runs.
- Direct pushes to `develop`, `main`, or unreviewed feature branches do not run
  the expensive PR workflow.
- Version tags matching `v*` run the Docker release/sign/GitHub Release
  workflow.
- The old weekly clean-room schedule and job are intentionally removed; use
  local `make ci-full` when clean-room validation is needed.

## Required CircleCI Environment

Create restricted project environment variables or contexts for:

- `DHI_USERNAME`
- `DHI_TOKEN`
- `GHCR_USERNAME`
- `GHCR_TOKEN` with package write access
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `GITHUB_RELEASE_TOKEN` with contents write access
- `GITHUB_CODEQL_TOKEN` with `security_events` write access
- `GITHUB_TOKEN` or `GH_TOKEN` with pull request read access for release-sync base detection

Create the GitHub repository secret `CIRCLECI_TOKEN` with permission to trigger
CircleCI pipelines. The lightweight GitHub label bridge uses it to start the
full PR gate after `ci:full` is applied.

Cosign uses CircleCI OIDC through `CIRCLE_OIDC_TOKEN_V2`. The signing job derives
the certificate issuer and identity from the token used to sign, verifies both
published registries by digest, and passes the verification values to the GitHub
Release helper.

## Migration Notes

- CodeQL runs through the CodeQL CLI and uploads SARIF to GitHub code scanning.
  It is part of `security-required`, so CodeQL setup/upload failures block the
  required security aggregate.
- `gitleaks`, `actionlint`, and `grype` are pinned to immutable image digests.
- The parallelism and in-job worker defaults are intentionally tunable:
  `python_test_parallelism=6`, `python_test_workers=4`,
  `e2e_parallelism=4`, and `e2e_workers=1`.
- A custom Pullbox CI image with Python, Node, browser OS deps, actionlint,
  gitleaks, grype, cosign, and gh preinstalled would likely reduce cold-start
  overhead further once the workflow shape is stable.

## Expected Required Checks

After migration, branch protection should point at the CircleCI aggregate jobs:

- `ci/circleci: ci-required`
- `ci/circleci: security-required`
- `ci/circleci: workflow-hygiene-required`

Docker Validate can remain non-required if it stays path-gated, matching the
current GitHub Actions behavior.

The legacy GitHub Actions Docker release workflow must not run on release tag
pushes after this migration. CircleCI is the release publisher for `v*` tags.
