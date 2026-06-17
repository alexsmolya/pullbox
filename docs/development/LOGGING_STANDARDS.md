# Pullbox Logging Standards

**Author:** Adam Hernandez
**Version:** 1.0
**Last Modified:** 2026-05-15

## Purpose

This document is the working logging reference for Pullbox contributors. It
explains which log planes exist, what belongs in each one, how structured fields
should be named, and how logs stay useful without leaking secrets.

Good logging should make troubleshooting easier for operators and maintainers.
It should not turn normal app usage into noise, and it should never expose
credentials, tokens, or sensitive local details.

## Current Baseline Notes

- Pullbox uses `structlog` for structured runtime logging.
- `src/pullbox/logging.py` configures console and file logging.
- `src/pullbox/core/log_sanitizer.py` redacts sensitive values.
- Sanitization runs after exception formatting so traceback text is also
  scrubbed.
- Startup output is mirrored to `/data/logs/startup.log` in Docker.
- Import and utility workflows have both operator summaries and detailed
  workflow-specific logs.
- Audit logs are separate from troubleshooting logs and track security-relevant
  events.
- Request logging includes request IDs through structlog context variables.

## Table of Contents

1. [Log Planes](#1-log-planes)
2. [Structured Fields](#2-structured-fields)
3. [Severity Rules](#3-severity-rules)
4. [Event Naming](#4-event-naming)
5. [Sanitization](#5-sanitization)
6. [Request Logging](#6-request-logging)
7. [Task And Scheduler Logging](#7-task-and-scheduler-logging)
8. [Import And Utility Logging](#8-import-and-utility-logging)
9. [Audit Events](#9-audit-events)
10. [Logging Audit Checklist](#10-logging-audit-checklist)

## 1. Log Planes

### 1.1 Current Pullbox implementation

Pullbox uses several log planes:

| Plane | Purpose |
|---|---|
| `pullbox.log` | Sparse operator/runtime summaries mirrored to stdout |
| `imports.log` | Detailed import workflow trace after sanitization |
| `utilities.log` | Per-item utility execution detail |
| import job logs | Database-backed import workflow history |
| utility job logs | Database-backed utility run detail |
| audit log | Security-relevant event history |
| health history | Stored component health outcomes and run history |
| `/data/logs/startup.log` | Docker startup and bootstrap transcript |

### 1.2 Required standard

- Keep `pullbox.log` summary-oriented.
- Put workflow detail into import, utility, or job-specific logs.
- Keep audit events separate from diagnostic logs.
- Keep health history focused on monitored component outcomes.
- Startup logs should help operators confirm migrations, paths, and app startup.
- Log planes that persist data must sanitize before persistence.

### 1.3 Current repo nuances

- Dozzle and `docker logs` show stdout/stderr. Operators often start there.
- `/data/logs` is the durable support surface for container deployments.
- Database-backed job logs power UI history and review screens, so they need
  enough detail to explain what happened without requiring file-log access.

### 1.4 Audit checks

- [ ] Operator logs stay concise.
- [ ] Workflow details go to the right workflow log plane.
- [ ] Audit events are not replaced by normal debug logs.
- [ ] Persisted logs are sanitized before storage.
- [ ] Startup logs remain useful for support.

## 2. Structured Fields

### 2.1 Current Pullbox implementation

Pullbox uses stable structured fields across runtime, task, request, import, and
utility logs where available.

Common fields:

```text
request_id
run_id
task_id
trigger_type
job_id
item_id
series_id
issue_id
client_id
attempt
duration_ms
outcome
```

### 2.2 Required standard

- Reuse established field names instead of inventing near-duplicates.
- Put variable data in fields, not event names.
- Use IDs when they help connect UI state, database state, and logs.
- Use `duration_ms` for elapsed milliseconds.
- If a duration exceeds 1000 ms and is displayed in UI, format it consistently
  with the app duration display rules.
- Keep structured fields small, JSON-friendly, and safe to persist.

### 2.3 Current repo nuances

- Not every event needs every field.
- A small, consistent field set is better than a giant one-off payload.
- Search and matching logs can be detailed at debug level, but high-cardinality
  detail should not flood normal operator logs.

### 2.4 Audit checks

- [ ] Existing field names are reused.
- [ ] Variable data is stored in fields, not event names.
- [ ] Durations use `duration_ms`.
- [ ] Fields are safe to serialize and persist.
- [ ] High-cardinality detail stays out of normal info logs.

## 3. Severity Rules

### 3.1 Current Pullbox implementation

The app uses standard levels: `debug`, `info`, `warning`, `error`, and
`exception`.

### 3.2 Required standard

- `debug` is for curated diagnostic detail: scoring, candidate evaluation,
  provider successes, retries, and fallback behavior.
- `info` is for concise operator-facing lifecycle summaries, actionable config
  changes, recoveries, and completed operations worth keeping.
- `warning` is for degraded-but-recoverable behavior, rejected requests, slow
  operations, backoff or disable transitions, and recoverable failures that may
  need attention.
- `error` is for request-level or operation-level failures that should stand out
  immediately but do not need a traceback.
- `exception` is for unexpected failures where traceback materially helps
  debugging.

### 3.3 Current repo nuances

- Expected skips are not always warnings. If no operator action is needed, use
  `info` or `debug`.
- Repeated known degraded states can use warning deduplication. Do not suppress
  real failures, lock contention, or security-relevant warnings.

### 3.4 Audit checks

- [ ] Routine successes do not spam `info`.
- [ ] Operator-actionable degraded states use `warning`.
- [ ] Unexpected failures use `exception` when traceback helps.
- [ ] Expected skips are not over-promoted to warnings.
- [ ] Deduplication does not hide real failures.

## 4. Event Naming

### 4.1 Current Pullbox implementation

- Event names are generally concise snake-case strings.
- Many events use outcome-oriented names such as `http_request_failed`,
  `task_started`, and `search_indexer_disabled`.

### 4.2 Required standard

- Event names use `snake_case`.
- Prefer outcome-oriented names.
- Avoid embedding variable data in event names.
- Keep names stable because tests, dashboards, and support habits may depend on
  them.
- Use namespaced logger names for log planes, not dotted event names unless the
  existing call site already uses one.

### 4.3 Current repo nuances

- Some older event names may use dotted segments. New events should prefer
  snake-case unless matching a local convention is more important.

### 4.4 Audit checks

- [ ] New event names are concise snake-case.
- [ ] Event names describe what happened.
- [ ] Variable data lives in fields.
- [ ] Existing event names are not renamed casually.

## 5. Sanitization

### 5.1 Current Pullbox implementation

`src/pullbox/core/log_sanitizer.py` redacts:

- passwords
- API keys
- bearer tokens
- secret keys
- URL query tokens
- credentials embedded in URLs or DSNs
- secret-looking `key=value` strings

### 5.2 Required standard

- All log sinks must redact sensitive data.
- Sanitization must happen before database persistence, not only before file or
  console rendering.
- Exception text and traceback rendering must be sanitized.
- Do not log raw request headers, cookies, session tokens, API keys, provider
  credentials, encryption keys, or connection strings.
- Prefer safe identifiers over raw user or credential material.

### 5.3 Current repo nuances

- Sanitization is a safety net, not permission to log sensitive values.
- Debug logging is still logging. It must follow the same secret rules.
- Diagnostic packages and support bundles need the same redaction discipline.

### 5.4 Audit checks

- [ ] New log sinks use the sanitizer.
- [ ] Database-backed logs sanitize before persistence.
- [ ] Tracebacks are sanitized after formatting.
- [ ] Raw secrets, tokens, cookies, and credentials are not logged.
- [ ] Diagnostic exports do not include unsanitized secret material.

## 6. Request Logging

### 6.1 Current Pullbox implementation

- Request middleware binds `request_id` through structlog context variables.
- At normal info level, operators reliably see important failures and degraded
  behavior.
- Routine successful requests can stay at debug level.

### 6.2 Required standard

At normal `INFO` level, operators should reliably see:

- `5xx` request failures
- slow requests
- auth/security-relevant `4xx` responses
- task or job start, complete, fail, cancel, and recover summaries
- concise import and utility lifecycle summaries
- meaningful config and startup/runtime fingerprint events

Routine successful requests can stay at `debug`.

### 6.3 Current repo nuances

- Not every `4xx` is security-relevant. Keep noisy client mistakes out of normal
  operator logs unless the pattern matters.
- Request logs should help correlate UI behavior, API behavior, and backend
  failures without exposing request bodies or secrets.

### 6.4 Audit checks

- [ ] Request logs include `request_id`.
- [ ] `5xx` failures are visible at normal logging levels.
- [ ] Slow requests are visible.
- [ ] Auth/security-relevant `4xx` responses are visible.
- [ ] Routine successes do not drown out important events.

## 7. Task And Scheduler Logging

### 7.1 Current Pullbox implementation

- Scheduled tasks and background workflows emit lifecycle events.
- Task stats and run history support System Tasks UI visibility.
- Some task flows bind run/task context into logs.

### 7.2 Required standard

- Every scheduled task run should carry a `run_id`.
- Task logs should include `task_id`, `trigger_type`, and `run_id` when
  available.
- Keep lightweight persisted run history so the System Tasks UI can show recent
  executions without requiring operators to grep `pullbox.log`.
- Use `info` for task start and complete summaries.
- Use `warning` for expected skips only when the operator likely needs to act.
- Use `exception` for unexpected task failures where traceback helps.

### 7.3 Current repo nuances

- Task logging needs to balance UI history and operator logs. Persisted history
  can be detailed without flooding stdout.

### 7.4 Audit checks

- [ ] Scheduled task runs include `run_id` where available.
- [ ] Task logs include useful task context.
- [ ] Task start and complete summaries are visible.
- [ ] Expected skips use the right severity.
- [ ] Persisted task history is enough for the UI.

## 8. Import And Utility Logging

### 8.1 Current Pullbox implementation

- Import workflows mirror summary events to operator logs and detail events to
  import-specific logs.
- Utility execution detail is written to utility-specific logs and job detail.
- Tests cover utility logging visibility and filtering behavior.

### 8.2 Required standard

- Import summaries should be concise and operator-readable.
- Import detail logs should explain per-item matching, file, and failure
  outcomes.
- Utility logs should preserve enough per-item context to review what happened.
- Utility failures should identify the item, operation, and outcome.
- Avoid duplicating every detail event into `pullbox.log`.

### 8.3 Current repo nuances

- Import and utility screens depend on persisted detail. File logs alone are not
  enough.
- Per-item logs can get large, so avoid dumping huge payloads or repeated raw
  provider data.

### 8.4 Audit checks

- [ ] Summary events stay concise.
- [ ] Detail events go to workflow-specific logs.
- [ ] Per-item failures include useful identifiers.
- [ ] Large raw payloads are not logged.
- [ ] Logs shown in UI are sanitized.

## 9. Audit Events

### 9.1 Current Pullbox implementation

- Security-relevant events are stored in the audit log.
- Auth, API key, session, password, username, security config, and local auth
  bypass events are represented.
- Audit logs are intentionally separate from normal troubleshooting logs.

### 9.2 Required standard

- Audit events should capture enough context for later review:
  - timestamp
  - actor
  - source IP where applicable
  - event type
  - outcome or reason
- Audit logs must not store raw secrets, tokens, or credentials.
- Security-relevant configuration changes must be auditable.
- Audit logging failure should not leak secrets.

### 9.3 Current repo nuances

- Audit logs are not a debug stream. Do not use them for general troubleshooting
  chatter.
- Any future retention policy must be explicit and tested.

### 9.4 Audit checks

- [ ] Security-relevant actions emit audit events.
- [ ] Audit entries include useful actor and source context.
- [ ] Audit entries do not store raw secrets or tokens.
- [ ] Audit events remain distinct from runtime debug logs.

## 10. Logging Audit Checklist

Use this checklist when adding or changing logs:

- [ ] Event name is concise snake-case.
- [ ] Variable data is in structured fields.
- [ ] Established field names are reused.
- [ ] Severity matches operator impact.
- [ ] Routine success stays out of normal info logs.
- [ ] Unexpected failures use `exception` when traceback helps.
- [ ] Secrets, tokens, cookies, and credentials are not logged.
- [ ] Persisted logs sanitize before storage.
- [ ] Import and utility detail goes to the right log plane.
- [ ] Request logs include `request_id` where available.
- [ ] Task logs include `run_id` where available.
- [ ] Audit events are used for security history, not debug chatter.
