"""Reusable baseline measurement helpers for the Performance sprint."""

from __future__ import annotations

import argparse
import gzip
import http.cookiejar
import json
import math
import os
import platform
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

MEASUREMENT_VERSION = "1.0"
DEFAULT_ENDPOINT = "Ping=/ping"
DEFAULT_STATIC_ASSET = "Tailwind CSS=src/pullbox/ui/static/css/tailwind.css"


@dataclass(frozen=True)
class EndpointSpec:
    """HTTP endpoint to measure, with a human-readable report label."""

    label: str
    target: str


@dataclass(frozen=True)
class FetchResult:
    """Single HTTP sample result."""

    status_code: int
    elapsed_ms: float
    content_length: int


@dataclass(frozen=True)
class FileSizeMeasurement:
    """Raw and gzip size for a static asset or other local file."""

    label: str
    path: str
    exists: bool
    raw_bytes: int | None
    gzip_bytes: int | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": self.path,
            "exists": self.exists,
            "raw_bytes": self.raw_bytes,
            "gzip_bytes": self.gzip_bytes,
            "error": self.error,
        }


@dataclass(frozen=True)
class HttpEndpointMeasurement:
    """Summary for one measured HTTP endpoint."""

    label: str
    url: str
    samples_requested: int
    samples_completed: int
    status_codes: dict[str, int]
    errors: list[str]
    timing_ms: dict[str, float | int] | None
    content_length_bytes: dict[str, float | int] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "url": self.url,
            "samples_requested": self.samples_requested,
            "samples_completed": self.samples_completed,
            "status_codes": self.status_codes,
            "errors": self.errors,
            "timing_ms": self.timing_ms,
            "content_length_bytes": self.content_length_bytes,
        }


class Fetcher(Protocol):
    """Callable used to collect one HTTP timing sample."""

    def __call__(self, url: str, timeout: float) -> FetchResult: ...


class ResponseLike(Protocol):
    """Context-manager response shape returned by urllib."""

    status: int

    def __enter__(self) -> ResponseLike: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


class OpenerLike(Protocol):
    """Small opener shape needed for authenticated baseline requests."""

    def open(
        self,
        fullurl: str | urllib.request.Request,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> object: ...


def parse_endpoint_spec(raw: str) -> EndpointSpec:
    """Parse `Label=/path` or use the target as the label."""

    value = raw.strip()
    if not value:
        msg = "endpoint spec cannot be blank"
        raise ValueError(msg)

    if "=" not in value:
        return EndpointSpec(label=value, target=value)

    label, target = value.split("=", 1)
    label = label.strip()
    target = target.strip()
    if not label or not target:
        msg = f"invalid endpoint spec: {raw!r}"
        raise ValueError(msg)
    return EndpointSpec(label=label, target=target)


def parse_header_spec(raw: str) -> tuple[str, str]:
    """Parse a CLI header spec as `Name: value` or `Name=value`."""

    value = raw.strip()
    separator = ":" if ":" in value else "=" if "=" in value else None
    if separator is None:
        msg = f"invalid header spec: {raw!r}"
        raise ValueError(msg)
    name, header_value = value.split(separator, 1)
    name = name.strip()
    header_value = header_value.strip()
    if not name or not header_value:
        msg = f"invalid header spec: {raw!r}"
        raise ValueError(msg)
    return name, header_value


def summarize_numbers(values: Sequence[float]) -> dict[str, float | int]:
    """Return min/median/nearest-rank p95/max for a non-empty numeric sample."""

    if not values:
        msg = "cannot summarize an empty sample"
        raise ValueError(msg)

    sorted_values = sorted(float(value) for value in values)
    p95_index = max(0, math.ceil(len(sorted_values) * 0.95) - 1)
    return {
        "samples": len(sorted_values),
        "min": round(sorted_values[0], 3),
        "median": round(float(statistics.median(sorted_values)), 3),
        "p95": round(sorted_values[p95_index], 3),
        "max": round(sorted_values[-1], 3),
    }


def resolve_endpoint_url(base_url: str, target: str) -> str:
    """Resolve a path-like endpoint target against a base URL."""

    if target.startswith(("http://", "https://")):
        return target
    return f"{base_url.rstrip('/')}/{target.lstrip('/')}"


def _validate_http_url(url: str) -> None:
    """Allow the baseline harness to fetch only HTTP(S) URLs."""

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"baseline fetch URLs must use http or https: {url!r}"
        raise ValueError(msg)


def _fetch_url(
    url: str,
    timeout: float,
    *,
    ssl_context: ssl.SSLContext | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch one URL using the standard library so the harness stays lightweight."""

    _validate_http_url(url)
    request_headers = {"User-Agent": f"PullboxPerformanceBaseline/{MEASUREMENT_VERSION}"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    started_at = time.perf_counter()
    try:
        # `_validate_http_url` rejects file/custom schemes before this call.
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:  # nosec B310
            body = response.read()
            status_code = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status_code = exc.code
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    return FetchResult(
        status_code=int(status_code),
        elapsed_ms=elapsed_ms,
        content_length=len(body),
    )


def default_fetcher(url: str, timeout: float) -> FetchResult:
    """Fetch one URL using normal TLS certificate verification."""

    return _fetch_url(url, timeout)


def create_fetcher(
    *,
    verify_tls: bool = True,
    headers: dict[str, str] | None = None,
) -> Fetcher:
    """Create a fetcher, optionally allowing local self-signed HTTPS certificates."""

    # `verify_tls=False` is an explicit local benchmark option for self-signed HTTPS.
    ssl_context = None if verify_tls else ssl._create_unverified_context()  # nosec B323

    def fetcher(url: str, timeout: float) -> FetchResult:
        return _fetch_url(url, timeout, ssl_context=ssl_context, headers=headers)

    return fetcher


def _fetch_with_opener(
    opener: OpenerLike,
    url: str,
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    _validate_http_url(url)
    request_headers = {"User-Agent": f"PullboxPerformanceBaseline/{MEASUREMENT_VERSION}"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    started_at = time.perf_counter()
    try:
        with cast("ResponseLike", opener.open(request, timeout=timeout)) as response:
            body = response.read()
            status_code = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status_code = exc.code
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    return FetchResult(
        status_code=int(status_code),
        elapsed_ms=elapsed_ms,
        content_length=len(body),
    )


def login_and_create_fetcher(
    *,
    base_url: str,
    login_url: str,
    username: str,
    password: str,
    timeout: float,
    verify_tls: bool = True,
    headers: dict[str, str] | None = None,
) -> Fetcher:
    """Create a session-cookie fetcher by logging into the local Pullbox app."""

    # `verify_tls=False` is an explicit local benchmark option for self-signed HTTPS.
    ssl_context = None if verify_tls else ssl._create_unverified_context()  # nosec B323
    cookie_jar = http.cookiejar.CookieJar()
    handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPCookieProcessor(cookie_jar)]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)

    login_target = resolve_endpoint_url(base_url, login_url)
    _validate_http_url(login_target)
    payload = json.dumps(
        {"username": username, "password": password},
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        login_target,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"PullboxPerformanceBaseline/{MEASUREMENT_VERSION}",
        },
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        response.read()
        if response.status >= 400:
            msg = f"benchmark login failed with status {response.status}"
            raise RuntimeError(msg)

    def fetcher(url: str, request_timeout: float) -> FetchResult:
        return _fetch_with_opener(opener, url, request_timeout, headers=headers)

    return cast("Fetcher", fetcher)


def measure_http_endpoint(
    spec: EndpointSpec,
    *,
    base_url: str,
    samples: int,
    timeout: float,
    fetcher: Fetcher = default_fetcher,
) -> HttpEndpointMeasurement:
    """Measure one HTTP endpoint repeatedly and return a compact summary."""

    if samples < 1:
        msg = "samples must be at least 1"
        raise ValueError(msg)

    url = resolve_endpoint_url(base_url, spec.target)
    timings: list[float] = []
    content_lengths: list[float] = []
    errors: list[str] = []
    status_codes: Counter[str] = Counter()

    for _ in range(samples):
        try:
            result = fetcher(url, timeout)
        except Exception as exc:  # pragma: no cover - exact network errors are environment-specific
            errors.append(f"{type(exc).__name__}: {exc}")
            continue

        timings.append(result.elapsed_ms)
        content_lengths.append(float(result.content_length))
        status_codes[str(result.status_code)] += 1

    return HttpEndpointMeasurement(
        label=spec.label,
        url=url,
        samples_requested=samples,
        samples_completed=len(timings),
        status_codes=dict(sorted(status_codes.items())),
        errors=errors,
        timing_ms=summarize_numbers(timings) if timings else None,
        content_length_bytes=summarize_numbers(content_lengths) if content_lengths else None,
    )


def measure_file_size(label: str, path: Path) -> FileSizeMeasurement:
    """Measure raw and gzip bytes for a local file."""

    resolved = path.resolve()
    if not resolved.exists():
        return FileSizeMeasurement(
            label=label,
            path=str(resolved),
            exists=False,
            raw_bytes=None,
            gzip_bytes=None,
            error="file does not exist",
        )

    try:
        content = resolved.read_bytes()
    except OSError as exc:
        return FileSizeMeasurement(
            label=label,
            path=str(resolved),
            exists=True,
            raw_bytes=None,
            gzip_bytes=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    return FileSizeMeasurement(
        label=label,
        path=str(resolved),
        exists=True,
        raw_bytes=len(content),
        gzip_bytes=len(gzip.compress(content)),
    )


def parse_static_asset_spec(raw: str, repo_root: Path) -> tuple[str, Path]:
    """Parse `Label=path` for a local static asset measurement."""

    value = raw.strip()
    if not value:
        msg = "static asset spec cannot be blank"
        raise ValueError(msg)

    if "=" in value:
        label, target = value.split("=", 1)
        label = label.strip()
        target = target.strip()
    else:
        target = value
        label = Path(target).name

    if not label or not target:
        msg = f"invalid static asset spec: {raw!r}"
        raise ValueError(msg)

    path = Path(target).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return label, path


def _run_git(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip()
    return output or None


def collect_context(repo_root: Path) -> dict[str, object]:
    """Collect runtime and git context for a baseline report."""

    return {
        "measurement_version": MEASUREMENT_VERSION,
        "measured_at": datetime.now(UTC).isoformat(),
        "repo_root": str(repo_root.resolve()),
        "git_branch": _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _run_git(repo_root, "rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_run_git(repo_root, "status", "--short")),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }


def build_baseline_report(
    *,
    repo_root: Path,
    base_url: str,
    endpoints: Sequence[EndpointSpec],
    static_assets: Sequence[tuple[str, Path]],
    samples: int,
    timeout: float,
    verify_tls: bool = True,
    header_names: Sequence[str] | None = None,
    login_enabled: bool = False,
    fetcher: Fetcher = default_fetcher,
) -> dict[str, object]:
    """Build a JSON-serializable baseline report."""

    return {
        "context": collect_context(repo_root),
        "settings": {
            "base_url": base_url,
            "samples": samples,
            "timeout_seconds": timeout,
            "verify_tls": verify_tls,
            "headers": sorted(header_names or ()),
            "login_enabled": login_enabled,
        },
        "static_assets": [
            measure_file_size(label, path).to_dict() for label, path in static_assets
        ],
        "http_endpoints": [
            measure_http_endpoint(
                endpoint,
                base_url=base_url,
                samples=samples,
                timeout=timeout,
                fetcher=fetcher,
            ).to_dict()
            for endpoint in endpoints
        ],
    }


def write_report(report: dict[str, object], output_path: Path) -> None:
    """Write a baseline report as stable, pretty JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture Pullbox performance sprint baseline measurements.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used for relative paths and git context.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PULLBOX_BENCHMARK_BASE_URL", "http://127.0.0.1:8585"),
        help="Pullbox base URL for HTTP endpoint measurements.",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Endpoint to measure, as Label=/path or /path. Repeatable.",
    )
    parser.add_argument(
        "--static-asset",
        action="append",
        default=[],
        help="Static asset to measure, as Label=path or path. Repeatable.",
    )
    parser.add_argument("--samples", type=int, default=30, help="HTTP samples per endpoint.")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="Skip HTTP measurements and only capture local file/context data.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for local self-signed HTTPS baselines.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Request header as Name: value or Name=value. Repeatable.",
    )
    parser.add_argument(
        "--login-url",
        default=os.environ.get("PULLBOX_BENCHMARK_LOGIN_URL", "/api/v1/auth/login"),
        help="Login endpoint used with benchmark username/password.",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("PULLBOX_BENCHMARK_USERNAME"),
        help="Optional Pullbox username for authenticated baseline requests.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("PULLBOX_BENCHMARK_PASSWORD"),
        help="Optional Pullbox password for authenticated baseline requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Prints to stdout when omitted.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    endpoint_specs = [] if args.skip_http else args.endpoint or [DEFAULT_ENDPOINT]
    static_asset_specs = args.static_asset or [DEFAULT_STATIC_ASSET]

    endpoints = [parse_endpoint_spec(raw) for raw in endpoint_specs]
    static_assets = [parse_static_asset_spec(raw, repo_root) for raw in static_asset_specs]
    headers = dict(parse_header_spec(raw) for raw in args.header)
    login_enabled = bool(args.username or args.password)
    if login_enabled and not (args.username and args.password):
        parser.error("--username and --password must be provided together")
    fetcher = (
        login_and_create_fetcher(
            base_url=args.base_url,
            login_url=args.login_url,
            username=args.username,
            password=args.password,
            timeout=args.timeout,
            verify_tls=not args.insecure,
            headers=headers,
        )
        if login_enabled
        else create_fetcher(verify_tls=not args.insecure, headers=headers)
    )
    report = build_baseline_report(
        repo_root=repo_root,
        base_url=args.base_url,
        endpoints=endpoints,
        static_assets=static_assets,
        samples=args.samples,
        timeout=args.timeout,
        verify_tls=not args.insecure,
        header_names=tuple(headers),
        login_enabled=login_enabled,
        fetcher=fetcher,
    )

    if args.output is not None:
        write_report(report, args.output)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    return 0
