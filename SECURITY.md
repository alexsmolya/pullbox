# Security Policy

Pullbox is a self-hosted application, so security has two sides: the app should
ship with safe defaults, and operators should have clear guidance for deploying
it responsibly. This document explains how to report vulnerabilities, what
security controls are currently in place, and which deployment settings deserve
extra attention.

Contributor-facing implementation standards live in
`docs/development/SECURITY_STANDARDS.md`.

## Reporting Vulnerabilities

Please report security vulnerabilities privately.

1. Do not open a public GitHub issue for a security vulnerability.
2. Use GitHub private vulnerability reporting from the repository Security tab
   when possible. This keeps triage in GitHub's advisory workflow.
3. If you cannot use GitHub private reporting, or if you need to coordinate
   outside GitHub, email `security@pullbox.app` with a short description,
   reproduction steps, affected version or commit when known, and any relevant
   logs or screenshots.
4. Reports are acknowledged within 48 hours.
5. The issue will be reviewed, fixed, and disclosed publicly only after a safe
   remediation path is available.

Helpful reports usually include:

- The vulnerable endpoint, workflow, or configuration.
- Whether authentication is required.
- Whether a default deployment is affected.
- Clear reproduction steps.
- Any proof-of-concept input needed to reproduce the issue.

## Architecture Security Overview

### Authentication

- Browser login uses signed session cookies.
- Session tokens are signed with `itsdangerous.URLSafeTimedSerializer` and the
  resolved application secret key from `PULLBOX_SECRET_KEY` or
  `/data/config.xml`.
- Session payloads contain only the user ID, a CSRF token, and a session version
  counter.
- Passwords are hashed with `bcrypt` using a cost factor of `12`.
- Password policy currently requires 8 to 128 characters, uppercase,
  lowercase, digit, and special character.
- Password input explicitly respects bcrypt's 72-byte input limit.
- Username and password changes increment the account session version, which
  invalidates existing browser sessions.
- API keys use the `pb_k1_` prefix, are shown once at creation, and are stored
  only as SHA-256 hashes.
- API keys support expiration, revocation, and last-used tracking.

### Authorization

- Requests authenticate through a browser session cookie, an `X-API-Key`
  header, or explicitly configured local auth bypass.
- Local auth bypass is disabled by default.
- Local auth bypass requires configured trusted local addresses or CIDR ranges.
- Trusted proxy headers are accepted only from configured proxy addresses.
- Local bypass writes still require CSRF protection.
- Public unauthenticated routes are limited to login, setup, static assets, and
  lightweight health checks such as `/ping`.

### CSRF Protection

- State-changing browser-session requests require a CSRF token.
- Protected methods include `POST`, `PUT`, `PATCH`, and `DELETE`.
- Token comparison uses constant-time comparison.
- API-key requests are exempt because API keys are sent through explicit
  headers instead of ambient browser cookies.
- Setup, login, logout, `/ping`, and health-check routes are intentionally
  exempt where needed for bootstrapping or monitoring.

### Secret Storage

- Provider credentials, indexer keys, download-client passwords, and similar
  integration secrets are encrypted at rest.
- Encryption uses Fernet with key material derived from the resolved
  application secret key.
- `/data/config.xml` is generated on first startup when it does not exist.
  Normal Docker installs can leave `PULLBOX_SECRET_KEY` unset and let Pullbox
  persist a strong generated `<SecretKey>` there.
- `PULLBOX_SECRET_KEY`, when set, overrides `config.xml` at runtime and is
  validated to reject weak, default, sample, or low-variety values outside
  explicit test paths.
- Raw API keys are never stored after creation.
- Logs and diagnostics should not expose secrets, authorization headers, bearer
  tokens, cookies, or credential-bearing URL query parameters.

### Transport Security

- HTTPS is recommended for every production deployment.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and marked `Secure` when the
  request is HTTPS.
- Trusted reverse-proxy deployments can set secure cookies through
  `X-Forwarded-Proto=https` when the proxy IP is configured in
  `PULLBOX_TRUSTED_PROXIES`.
- `Strict-Transport-Security` is sent in production mode.
- Security headers include `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, and `Content-Security-Policy`.
- The current Content Security Policy still allows inline script/style required
  by the server-rendered UI stack. The app-side policy also allows
  `'unsafe-eval'` for current frontend behavior. Tightening CSP remains future
  hardening work.

### Input Validation

- Filesystem browsing validates requested paths against blocked system
  locations and rejects traversal, null bytes, and non-printable characters.
- Backup, log, and file-download endpoints validate filenames through strict
  allowlist patterns.
- User search input escapes SQL wildcard characters before use in `LIKE` or
  `ILIKE` queries.
- Username input is limited to 3 to 50 characters and permits letters, numbers,
  underscores, and hyphens.
- Operator-configured peer URLs for indexers and download clients are expected
  to be explicit `http` or `https` service URLs.
- Pullbox does not expose a generic fetch-any-URL endpoint.

### Output Sanitization

- Production error responses hide stack traces, internal paths, and unexpected
  exception details.
- Production about and diagnostic surfaces redact filesystem paths where
  appropriate.
- Jinja templates rely on autoescaping by default.
- HTML coming from external metadata sources is sanitized before display.

### Logging And Audit Trail

- Application logs are structured and event-oriented.
- Sensitive fields are redacted before log output.
- URL query parameters containing secrets are scrubbed.
- Bearer tokens and authorization headers are stripped from logs.
- Security-relevant actions are recorded through audit logging where the app has
  a user-facing or operational review surface.
- Temporary debug logging is time-limited and restored from runtime settings on
  startup when still valid.

### Rate Limiting

- Login attempts use a sliding-window limiter with configurable thresholds per
  client IP.
- API traffic uses tiered rate limiting for expensive operations, write
  operations, and read operations.
- Rate limit behavior is enforced in middleware before route logic does
  heavyweight work.

### Database And Runtime

- SQLite database files are tightened to owner-only read/write permissions at
  startup when the runtime can apply file modes.
- SQLite enables foreign keys and a busy timeout.
- SQLite journal mode is configurable. The default app setting and Docker
  examples use `WAL`; `DELETE` remains an allowed override for constrained
  deployments.
- Stale SQLite sidecar files can be quarantined when the main database remains
  readable.
- Production Docker builds use Docker Hardened Images through
  `docker/Dockerfile`.
- The production container runs as a non-root user and keeps app data in
  explicit runtime directories.

## Configuration Security Checklist

- [ ] Keep `/data/config.xml` durable and backed up; it contains the generated
      application secret for normal Docker installs.
- [ ] If managing the secret with `PULLBOX_SECRET_KEY` instead of `config.xml`,
      set it to a stable random value and never rotate it without a migration
      plan.

  ```bash
  python -c "import secrets; print(secrets.token_hex(64))"
  ```

- [ ] Keep `PULLBOX_DEBUG=false` in production.
- [ ] Use HTTPS with a valid TLS certificate for browser access.
- [ ] Configure `PULLBOX_TRUSTED_PROXIES` when running behind nginx, Caddy,
      Traefik, or another reverse proxy.
- [ ] Review `PULLBOX_LOCAL_ADDRESSES` before enabling local auth bypass.
- [ ] Keep the SQLite database and config files outside any web-accessible
      directory.
- [ ] Set rate limits appropriate for the deployment.
- [ ] Rotate provider credentials and API keys after any suspected exposure.
- [ ] Keep the container image and Python dependencies current.

## Password Recovery

If access to the web UI is lost, reset the password from inside the running
container with the installed management CLI:

```bash
docker exec pullbox python -m pullbox.cli reset-password \
  --user admin \
  --password 'NewPass1!'
```

Use your actual container name if it is not `pullbox`. The command:

- Validates the new password against the current password policy.
- Updates the bcrypt hash in the database.
- Increments the user's session version, invalidating existing browser
  sessions.

## Known Limitations And Accepted Risks

1. **SABnzbd API key in URL parameters:** SABnzbd expects its API key as a URL
   query parameter. Pullbox redacts credential-bearing query parameters before
   log output.

2. **XML parsing with the standard library:** ComicInfo.xml parsing and
   Newznab/Torznab XML responses use Python's standard XML parser. These inputs
   come from local archive files and configured indexer APIs, not arbitrary
   unauthenticated request bodies.

3. **Content Security Policy still permits inline frontend behavior:** The
   current server-rendered UI stack requires inline script/style allowances.
   The app-side policy also permits `'unsafe-eval'`. This is documented and
   tested as current behavior, not treated as complete CSP hardening.

4. **Password blocklist checks are not enabled yet:** Passwords are validated
   for length, character classes, and bcrypt limits. Known-compromised password
   checks remain future hardening work.

## Running Security Checks

Run the project security check script:

```bash
bash scripts/security_check.sh
```

Useful focused checks:

```bash
pip-audit
bandit -r src/pullbox/ -ll -q
pytest tests/unit/test_csrf.py \
       tests/unit/test_cookie_flags.py \
       tests/unit/test_password_policy.py \
       tests/unit/test_password_storage_security_contracts.py \
       tests/unit/test_api_key_security.py \
       tests/unit/test_filename_validation.py \
       tests/unit/test_local_auth_bypass.py \
       tests/unit/test_log_sanitizer.py \
       tests/unit/test_secret_storage_contracts.py \
       tests/unit/test_secret_validation.py \
       tests/unit/test_security_headers.py \
       tests/unit/test_session_lifecycle.py \
       tests/unit/test_database_permissions.py \
       tests/unit/test_reset_password.py \
       tests/unit/test_sql_escape.py \
       tests/unit/test_sql_injection_contract.py -v
```
