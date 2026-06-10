# Pullbox Code Standards

**Author:** Adam Hernandez  
**Version:** 1.0  
**Last Modified:** 2026-05-15  

## Purpose

This document is the working code reference for Pullbox contributors. It
captures how the codebase is written today, the standards new code should
follow, and the checks that keep changes readable, typed, tested, and safe to
review.

The goal is not clever code. The goal is code that is easy to trace, easy to
test, honest about failure, and boring in the best possible way.

## Current Baseline Notes

- Pullbox supports Python 3.12 and newer.
- Python 3.14 is the primary production container runtime.
- Ruff handles linting and formatting.
- mypy runs in strict mode against `src/pullbox/` with `python_version = "3.12"`
  so compatibility stays honest.
- pytest is the main test runner.
- Playwright-backed E2E tests cover Chromium, Firefox, and accessibility flows.
- Runtime database access is async SQLAlchemy.
- HTTP clients use `httpx.AsyncClient` with explicit timeout behavior.
- TDD is the expected development workflow for behavior changes.
- UI work follows `docs/development/DESIGN_SYSTEM.md` and
  `docs/development/ACCESSIBILITY_STANDARDS.md`.
- Database work follows `docs/development/DATABASE_STANDARDS.md`.
- Security-sensitive work follows `docs/development/SECURITY_STANDARDS.md`.

## Table of Contents

1. [Python And Typing](#1-python-and-typing)
2. [Formatting And Imports](#2-formatting-and-imports)
3. [Error Handling And Logging](#3-error-handling-and-logging)
4. [Async And I/O](#4-async-and-io)
5. [Database Access](#5-database-access)
6. [Configuration And Secrets](#6-configuration-and-secrets)
7. [HTTP Clients](#7-http-clients)
8. [Schemas And API Routes](#8-schemas-and-api-routes)
9. [Files, Paths, And Archives](#9-files-paths-and-archives)
10. [Frontend Code](#10-frontend-code)
11. [Testing And TDD](#11-testing-and-tdd)
12. [Validation Gates](#12-validation-gates)
13. [Documentation And Comments](#13-documentation-and-comments)
14. [Workflow Code](#14-workflow-code)
15. [Code Review Checklist](#15-code-review-checklist)

## 1. Python And Typing

### 1.1 Current Pullbox implementation

- `pyproject.toml` requires Python `>=3.12`.
- Ruff targets Python 3.12 syntax.
- mypy runs with `strict = true`.
- Runtime code uses modern type syntax such as `list[str]` and
  `Series | None`.
- Pydantic's mypy plugin is enabled.

### 1.2 Required standard

- Function signatures include parameter and return annotations.
- Non-obvious variables should be annotated.
- Use built-in generic types: `list`, `dict`, `tuple`, `set`.
- Use `X | None` instead of `Optional[X]`.
- Use `collections.abc` for callable, iterable, mapping, and sequence
  interfaces.
- Avoid `Any` unless the boundary is genuinely dynamic and the reason is local.
- Do not silence mypy with broad ignores. Narrow the type or isolate the
  boundary instead.

```python
from collections.abc import Sequence

async def get_series(session: AsyncSession, series_id: int) -> Series | None:
    result = await session.execute(select(Series).where(Series.id == series_id))
    return result.scalar_one_or_none()


def normalize_ids(ids: Sequence[int]) -> list[int]:
    return sorted(set(ids))
```

### 1.3 Current repo nuances

- mypy checks Python 3.12 compatibility even though the production container is
  on Python 3.14.
- `from __future__ import annotations` may remain in files that already use it.
  Removing it is not required unless a touched file has a clear reason.
- Boundary code that receives untyped third-party data should convert it into a
  typed internal shape quickly.

### 1.4 Audit checks

- [ ] New functions have parameter and return annotations.
- [ ] Modern built-in generic syntax is used.
- [ ] `Any` is avoided or isolated at a real dynamic boundary.
- [ ] mypy strict passes without broad ignores.

## 2. Formatting And Imports

### 2.1 Current Pullbox implementation

- Ruff is the formatter and linter.
- Import sorting is handled by Ruff.
- `make lint` runs `ruff check src/ tests/`.
- `make format` runs `ruff format --check src/ tests/`.
- `make format-fix` applies formatting.

### 2.2 Required standard

- Let Ruff format code.
- Do not hand-align imports or spacing in ways that fight the formatter.
- Imports should stay grouped in the standard order:
  1. standard library
  2. third-party packages
  3. Pullbox modules
- Prefer clear module imports over clever aliasing.
- Avoid unused imports, dead code, and commented-out code.

### 2.3 Current repo nuances

- If Ruff and personal preference disagree, Ruff wins.
- Generated or migration code can have local exceptions, but runtime code should
  stay clean.

### 2.4 Audit checks

- [ ] `make lint` passes.
- [ ] `make format` passes.
- [ ] Imports are sorted by the configured tool.
- [ ] No dead imports or commented-out implementation code are added.

## 3. Error Handling And Logging

### 3.1 Current Pullbox implementation

- Domain services raise domain-specific exceptions where possible.
- Routes translate expected domain failures into safe API or UI responses.
- Generic unhandled errors return detailed messages only in debug mode.
- Structlog sanitization redacts secret-like data.
- Security-relevant events use audit logging where appropriate.

### 3.2 Required standard

- Catch specific exceptions.
- Preserve useful context when raising domain errors.
- Do not swallow exceptions silently.
- Do not log secrets, tokens, API keys, passwords, connection strings, or raw
  provider credentials.
- User-facing errors should be safe and actionable.
- Internal logs should help troubleshoot without leaking sensitive data.

```python
try:
    result = await provider.fetch_issue(issue_id)
except ProviderTimeoutError as exc:
    raise SearchProviderError("Provider timed out while fetching issue data") from exc
```

### 3.3 Current repo nuances

- Logging sanitization is a backstop, not permission to log secrets first.
- Some background jobs should continue after one item fails. In those cases, log
  the failure and keep item-level outcome state honest.
- Audit events are for security and operational accountability, not general
  debug logging.

### 3.4 Audit checks

- [ ] Exceptions are specific and preserve useful context.
- [ ] Expected failures have safe user-facing responses.
- [ ] Logs do not include secrets or raw tokens.
- [ ] Background loops record per-item failures instead of hiding them.

## 4. Async And I/O

### 4.1 Current Pullbox implementation

- Runtime database and HTTP work is async.
- Blocking archive, filesystem, or image operations are isolated from async
  request flow where needed.
- pytest uses `asyncio_mode = "auto"`.

### 4.2 Required standard

- Database queries are async.
- HTTP calls are async.
- Long-running blocking work must not run directly on the event loop.
- Use thread offloading or task processing for blocking filesystem, archive, or
  CPU-heavy operations.
- Do not hold database write transactions open across slow network or file work.

### 4.3 Current repo nuances

- Not every filesystem call needs a thread pool. The risk is slow or repeated
  blocking work inside hot async paths.
- Archive extraction and image work deserve extra care because they can block
  longer than expected.

### 4.4 Audit checks

- [ ] Async request paths do not run slow blocking work directly.
- [ ] HTTP and database operations are awaited.
- [ ] Blocking archive or image work is isolated when needed.
- [ ] Long task flows split database work from slow external work.

## 5. Database Access

### 5.1 Current Pullbox implementation

- Database sessions are SQLAlchemy `AsyncSession`.
- Request sessions use the shared `get_db()` dependency.
- Background tasks create short-lived sessions from the shared factory.
- SQLite uses WAL, foreign keys, busy timeout, and maintenance gate behavior.

### 5.2 Required standard

- Follow `docs/development/DATABASE_STANDARDS.md`.
- Services accept `AsyncSession` directly.
- Request-scoped services use `flush()` when generated IDs are needed.
- Request-scoped services avoid hidden commits.
- User input must not be interpolated into SQL.
- Static SQL is allowed only for narrow liveness, metadata, PRAGMA, diagnostic,
  or migration use.
- Relationship-heavy queries should load required relationships explicitly.

### 5.3 Current repo nuances

- Explicit commits are acceptable in task, lifecycle, startup, shutdown,
  scheduler, utility, and maintenance paths when those paths own the session.
- SQLite lock behavior makes transaction length a correctness concern, not just
  a performance concern.

### 5.4 Audit checks

- [ ] Runtime database access uses `AsyncSession`.
- [ ] Request routes use the shared session dependency.
- [ ] Services accept sessions, not factories.
- [ ] User-driven raw SQL is not introduced.
- [ ] Transaction boundaries are clear.

## 6. Configuration And Secrets

### 6.1 Current Pullbox implementation

- Runtime settings are centralized through config modules.
- Database-backed system config stores feature and integration settings.
- Provider credentials are encrypted at rest.
- Application secret strength is validated at startup.

### 6.2 Required standard

- Do not read environment variables ad hoc throughout the codebase.
- Use the established settings/config access path.
- Secrets must not be logged.
- New secret-bearing config values must be typed as secrets and encrypted at
  rest.
- Config validation should fail early with clear messages.

### 6.3 Current repo nuances

- Test config may use explicit test-only secret paths. Those paths must stay
  impossible to trigger accidentally in normal runtime.
- Operator-configured values still need validation because config is a trust
  boundary.

### 6.4 Audit checks

- [ ] Config access uses the established settings or system-config layer.
- [ ] Secret values are encrypted or hashed as appropriate.
- [ ] Secret values are not logged.
- [ ] Invalid config fails early and clearly.

## 7. HTTP Clients

### 7.1 Current Pullbox implementation

- Pullbox uses `httpx.AsyncClient`.
- Static checks reject `requests` imports in app code.
- Static checks reject `httpx.AsyncClient` construction without explicit timeout.
- Static checks reject literal `verify=False` call sites.
- Operator peer URLs use shared validation for scheme, host, credentials, and
  whitespace.

### 7.2 Required standard

- Use `httpx.AsyncClient`.
- Every outbound HTTP path has explicit timeout behavior.
- TLS verification is on by default.
- Any option to disable TLS verification must be explicit, narrow, and
  documented.
- Operator-configured peer URLs accept only `http` and `https`.
- Arbitrary user-supplied server-side fetch URLs are not allowed.

### 7.3 Current repo nuances

- Timeout can be request-level or client-level.
- Self-hosted peers can use local or private addresses, but that is different
  from accepting arbitrary request-driven URLs.

### 7.4 Audit checks

- [ ] Application code does not import `requests`.
- [ ] HTTP clients define timeout behavior.
- [ ] TLS verification is not disabled by default.
- [ ] Peer URLs are validated before use.
- [ ] Connectivity tests do not become open proxies.

## 8. Schemas And API Routes

### 8.1 Current Pullbox implementation

- FastAPI routes use Pydantic schemas for request and response contracts.
- Pydantic v2 is used.
- API routes rely on dependency injection for auth, sessions, and shared
  services.
- Browser-facing UI routes and JSON API routes are separate surfaces.

### 8.2 Required standard

- Request and response payloads should use explicit Pydantic models.
- Public schema fields should include useful descriptions when they appear in
  API docs.
- Route handlers stay thin.
- Business rules belong in services.
- Routes translate service outcomes into HTTP responses.
- Authorization and authentication dependencies should be visible at the route
  boundary.

### 8.3 Current repo nuances

- Not every internal helper needs a Pydantic model. External API boundaries do.
- UI routes may return templates or fragments, but they still need clear auth,
  CSRF, and error behavior.

### 8.4 Audit checks

- [ ] API payloads use explicit schemas.
- [ ] Route handlers stay thin.
- [ ] Business logic lives in services.
- [ ] Auth and authorization dependencies are clear.
- [ ] Error responses are safe and consistent.

## 9. Files, Paths, And Archives

### 9.1 Current Pullbox implementation

- `src/pullbox/core/file_safety.py` centralizes file and archive safety checks.
- `src/pullbox/core/naming.py` centralizes safe name handling.
- Import and post-processing flows validate paths and extensions before moving
  files into the library.

### 9.2 Required standard

- User-derived and provider-derived filenames must be sanitized.
- User-supplied paths must be resolved and checked against allowed roots.
- Archive member paths must be checked before extraction.
- Unsafe archive content fails closed where inspection is supported.
- File operations should be atomic where practical.

### 9.3 Current repo nuances

- Comic and archive workflows cross trust boundaries often. Treat provider
  filenames, torrent filenames, import paths, and archive members as untrusted.
- RAR/7z inspection has different toolchain constraints than ZIP/CBZ.

### 9.4 Audit checks

- [ ] Filenames are sanitized before filesystem use.
- [ ] Paths are resolved under allowed roots.
- [ ] Archive members are checked before extraction.
- [ ] Unsafe files fail closed.

## 10. Frontend Code

### 10.1 Current Pullbox implementation

- UI is server-rendered with Jinja templates, HTMX, Alpine, and Tailwind.
- Tailwind builds from `src/pullbox/ui/static/css/input.css`.
- Shared UI rules live in `docs/development/DESIGN_SYSTEM.md`.
- Accessibility rules live in `docs/development/ACCESSIBILITY_STANDARDS.md`.

### 10.2 Required standard

- Follow the design system for layout, tokens, components, and page blueprints.
- Follow accessibility standards for focus, contrast, keyboard behavior, and
  reduced motion.
- Prefer shared Jinja macros or components for repeated structures.
- Use `tojson` for structured JavaScript data injection.
- Do not add unsanitized HTML sinks.
- HTMX fragments should preserve auth, CSRF, and history behavior.

### 10.3 Current repo nuances

- Some older templates still contain bespoke styling. New work should not copy
  those patterns.
- UI behavior can be security behavior. Examples include CSRF headers,
  `hx-history="false"`, modal focus handling, and local auth warnings.

### 10.4 Audit checks

- [ ] Semantic tokens are used for styling changes.
- [ ] Shared UI components are used where they exist.
- [ ] Structured data uses `tojson`.
- [ ] UI changes are checked in light and dark mode.
- [ ] Accessibility behavior is preserved.

## 11. Testing And TDD

### 11.1 Current Pullbox implementation

- pytest covers unit, integration, API, provider, utility, and E2E tests.
- Test factories and fixtures are preferred over repeated setup.
- Database test sessions roll back where the fixture contract provides that
  behavior.
- Real-world fixtures exist for search and parsing edge cases.

### 11.2 Required standard

- Behavioral changes start with tests.
- Add failing characterization tests before changing existing behavior.
- Tests should cover happy paths, edge cases, and failure paths.
- Implementation should be the minimum code needed to pass the intended tests.
- Existing tests should not be weakened to fit a bug.
- Regression tests should stay close to the layer where the bug happened.

Recommended flow:

1. Read the existing code and tests.
2. Add or update the failing test.
3. Run the focused test and confirm the failure is meaningful.
4. Implement the smallest behavior change.
5. Run the focused test until it passes.
6. Run the relevant broader suite.
7. Run the full validation gate when the change is ready.

### 11.3 Current repo nuances

- A test that passes against a stub is probably not testing the intended
  behavior.
- For search, parsing, matching, and provider behavior, real fixture data is
  usually more valuable than invented examples.
- UI changes often need both template/unit coverage and browser coverage.

### 11.4 Audit checks

- [ ] New behavior has a failing test first.
- [ ] Edge cases and errors are covered.
- [ ] Existing tests are not weakened without a documented contract change.
- [ ] Real fixtures are used when realistic data matters.
- [ ] Focused and broader suites pass.

## 12. Validation Gates

### 12.1 Current Pullbox implementation

- `make validate` runs CSS build, lint, format, typecheck, and non-E2E tests.
- `make ci-local` mirrors the main CI shape locally.
- `make ci-full` adds security and Docker smoke validation.
- `make test-a11y` runs contrast and accessibility checks.
- E2E browser tests run in Chromium and Firefox.

### 12.2 Required standard

- Run the smallest useful focused test while developing.
- Run the relevant domain suite before handing off a feature or fix.
- Run `make validate` for ordinary code changes before final review.
- Run `make ci-full` when release, Docker, security, dependency, workflow, or
  broad cross-cutting changes are involved.
- CSS output must be rebuilt when Tailwind input or scan sources change.

### 12.3 Current repo nuances

- Full validation can take a while. That is not a reason to skip focused tests.
- E2E failures should be investigated from logs and artifacts before guessing.

### 12.4 Audit checks

- [ ] Focused tests pass.
- [ ] `make validate` passes for normal code changes.
- [ ] Browser tests pass for UI behavior changes.
- [ ] `make ci-full` passes for release or infrastructure-sensitive changes.
- [ ] Generated CSS is not stale.

## 13. Documentation And Comments

### 13.1 Current Pullbox implementation

- Modules generally have file-level docstrings when they provide meaningful
  context.
- Tests often use docstrings to explain behavior under test.
- Inline comments are used when code would be hard to understand without local
  context.

### 13.2 Required standard

- Comments explain why, not what.
- Avoid comments that repeat obvious code.
- Public classes and complex functions should have docstrings.
- Simple helpers with clear names do not need noisy docstrings.
- Security-sensitive code should document the trust boundary.
- TODO comments need a concrete reason or follow-up shape. Avoid vague TODOs.

```python
# ComicVine calls series "volumes"; normalize the provider term at the boundary.
provider_volume_id = payload["id"]
```

### 13.3 Current repo nuances

- Code comments are not a substitute for clear names.
- Test names and test docstrings should make the contract easy to spot during
  failure triage.
- User-facing copy belongs under the UI copy style rules, not in developer
  comments.

### 13.4 Audit checks

- [ ] Complex modules and public classes have useful docstrings.
- [ ] Inline comments explain non-obvious reasons.
- [ ] Security and data-boundary code documents the trust boundary.
- [ ] TODOs are specific enough to act on later.

## 14. Workflow Code

### 14.1 Current Pullbox implementation

- GitHub workflows use pinned actions with version comments.
- Workflows and jobs declare explicit permissions.
- `pull_request_target` is not used.
- Local workflow hygiene checks are available through the Makefile.

### 14.2 Required standard

- GitHub Actions are pinned to full commit SHAs with version comments.
- Workflows declare top-level default permissions.
- Jobs declare needed permissions explicitly.
- Do not use `pull_request_target`.
- New workflow secrets must be documented and scoped narrowly.
- CI behavior should be reproducible locally where practical.

### 14.3 Current repo nuances

- Workflow changes are supply-chain changes. Treat them with the same care as
  application security code.
- Comments that identify action versions are useful because full SHAs are not
  readable by themselves.

### 14.4 Audit checks

- [ ] Actions are full-SHA pinned with version comments.
- [ ] Workflow and job permissions are explicit.
- [ ] `pull_request_target` is absent.
- [ ] New secrets are documented and narrowly scoped.
- [ ] Local validation exists or the CI-only reason is documented.

## 15. Code Review Checklist

Use this checklist before marking a code change ready:

- [ ] Types are explicit and mypy strict passes.
- [ ] Ruff lint and format checks pass.
- [ ] Async paths do not block the event loop with slow work.
- [ ] Database session ownership and transaction boundaries are clear.
- [ ] SQL stays ORM/Core-first, with static SQL only for narrow exceptions.
- [ ] HTTP calls have explicit timeout behavior.
- [ ] Config and secret handling follows the established layers.
- [ ] User input is validated at the boundary.
- [ ] File and archive operations use safety helpers.
- [ ] UI changes follow design and accessibility standards.
- [ ] Tests cover behavior, edge cases, and failure paths.
- [ ] Regression tests are added for bug fixes.
- [ ] Logs and errors do not leak secrets.
- [ ] Workflow changes preserve pinned actions and explicit permissions.
