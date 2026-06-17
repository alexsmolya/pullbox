from __future__ import annotations

import io
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pullbox.performance import baseline
from pullbox.performance.baseline import (
    EndpointSpec,
    FetchResult,
    build_baseline_report,
    create_fetcher,
    default_fetcher,
    login_and_create_fetcher,
    measure_file_size,
    measure_http_endpoint,
    parse_endpoint_spec,
    parse_header_spec,
    parse_static_asset_spec,
    resolve_endpoint_url,
    summarize_numbers,
    write_report,
)


def test_parse_endpoint_spec_supports_labelled_paths() -> None:
    spec = parse_endpoint_spec("Ping=/ping")

    assert spec == EndpointSpec(label="Ping", target="/ping")


def test_parse_endpoint_spec_uses_target_as_default_label() -> None:
    spec = parse_endpoint_spec("/api/v1/series")

    assert spec == EndpointSpec(label="/api/v1/series", target="/api/v1/series")


@pytest.mark.parametrize("raw", ["", " =/ping", "Ping= "])
def test_parse_endpoint_spec_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_endpoint_spec(raw)


def test_parse_header_spec_supports_colon_separator() -> None:
    assert parse_header_spec("HX-Request:true") == ("HX-Request", "true")


def test_parse_header_spec_supports_equals_separator() -> None:
    assert parse_header_spec("X-API-Key=secret") == ("X-API-Key", "secret")


@pytest.mark.parametrize("raw", ["HX-Request", ":true", "HX-Request="])
def test_parse_header_spec_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_header_spec(raw)


def test_summarize_numbers_reports_nearest_rank_p95() -> None:
    summary = summarize_numbers([10.0, 20.0, 30.0, 40.0])

    assert summary == {
        "samples": 4,
        "min": 10.0,
        "median": 25.0,
        "p95": 40.0,
        "max": 40.0,
    }


def test_summarize_numbers_rejects_empty_samples() -> None:
    with pytest.raises(ValueError):
        summarize_numbers([])


def test_resolve_endpoint_url_preserves_absolute_urls() -> None:
    assert (
        resolve_endpoint_url("http://pullbox.test", "https://elsewhere.test/ping")
        == "https://elsewhere.test/ping"
    )


def test_measure_http_endpoint_collects_timing_and_status_counts() -> None:
    timings = [10.0, 20.0, 30.0, 40.0]

    def fake_fetcher(url: str, timeout: float) -> FetchResult:
        assert url == "http://pullbox.test/ping"
        assert timeout == 2.5
        return FetchResult(status_code=200, elapsed_ms=timings.pop(0), content_length=128)

    measurement = measure_http_endpoint(
        EndpointSpec(label="Ping", target="/ping"),
        base_url="http://pullbox.test",
        samples=4,
        timeout=2.5,
        fetcher=fake_fetcher,
    )

    assert measurement.to_dict() == {
        "label": "Ping",
        "url": "http://pullbox.test/ping",
        "samples_requested": 4,
        "samples_completed": 4,
        "status_codes": {"200": 4},
        "errors": [],
        "timing_ms": {
            "samples": 4,
            "min": 10.0,
            "median": 25.0,
            "p95": 40.0,
            "max": 40.0,
        },
        "content_length_bytes": {
            "samples": 4,
            "min": 128.0,
            "median": 128.0,
            "p95": 128.0,
            "max": 128.0,
        },
    }


def test_measure_http_endpoint_rejects_invalid_sample_count() -> None:
    with pytest.raises(ValueError):
        measure_http_endpoint(
            EndpointSpec(label="Ping", target="/ping"),
            base_url="http://pullbox.test",
            samples=0,
            timeout=1.0,
        )


def test_measure_file_size_reports_raw_and_gzip_bytes(tmp_path: Path) -> None:
    target = tmp_path / "tailwind.css"
    target.write_text(".test { color: red; }\n" * 20, encoding="utf-8")

    measurement = measure_file_size("tailwind", target)

    assert measurement.label == "tailwind"
    assert measurement.path == str(target)
    assert measurement.raw_bytes == target.stat().st_size
    assert measurement.gzip_bytes > 0


def test_measure_file_size_reports_missing_files(tmp_path: Path) -> None:
    measurement = measure_file_size("missing", tmp_path / "missing.css")

    assert measurement.to_dict() == {
        "label": "missing",
        "path": str(tmp_path / "missing.css"),
        "exists": False,
        "raw_bytes": None,
        "gzip_bytes": None,
        "error": "file does not exist",
    }


def test_measure_file_size_reports_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "blocked.css"
    target.write_text("blocked", encoding="utf-8")

    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("nope")))

    measurement = measure_file_size("blocked", target)

    assert measurement.exists is True
    assert measurement.raw_bytes is None
    assert measurement.gzip_bytes is None
    assert measurement.error == "OSError: nope"


def test_parse_static_asset_spec_supports_relative_paths(tmp_path: Path) -> None:
    label, path = parse_static_asset_spec("Tailwind=src/tailwind.css", tmp_path)

    assert label == "Tailwind"
    assert path == tmp_path / "src/tailwind.css"


def test_parse_static_asset_spec_defaults_label_from_path(tmp_path: Path) -> None:
    label, path = parse_static_asset_spec("/tmp/tailwind.css", tmp_path)

    assert label == "tailwind.css"
    assert path == Path("/tmp/tailwind.css")


@pytest.mark.parametrize("raw", ["", "Tailwind=", "=src/tailwind.css"])
def test_parse_static_asset_spec_rejects_invalid_values(raw: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        parse_static_asset_spec(raw, tmp_path)


def test_build_baseline_report_combines_context_static_assets_and_http(tmp_path: Path) -> None:
    css = tmp_path / "tailwind.css"
    css.write_text(".test { color: red; }\n", encoding="utf-8")

    def fake_fetcher(url: str, timeout: float) -> FetchResult:
        return FetchResult(status_code=200, elapsed_ms=12.5, content_length=len(url) + int(timeout))

    report = build_baseline_report(
        repo_root=tmp_path,
        base_url="http://pullbox.test",
        endpoints=[EndpointSpec(label="Ping", target="/ping")],
        static_assets=[("tailwind", css)],
        samples=2,
        timeout=1.0,
        fetcher=fake_fetcher,
    )

    assert report["context"]["repo_root"] == str(tmp_path)
    assert report["context"]["measurement_version"] == "1.0"
    assert report["static_assets"][0]["label"] == "tailwind"
    assert report["http_endpoints"][0]["label"] == "Ping"
    assert report["http_endpoints"][0]["samples_completed"] == 2


def test_default_fetcher_uses_standard_fetch_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        baseline,
        "_fetch_url",
        lambda url, timeout: FetchResult(
            status_code=204,
            elapsed_ms=timeout,
            content_length=len(url),
        ),
    )

    result = default_fetcher("https://pullbox.test/ping", 2.0)

    assert result == FetchResult(status_code=204, elapsed_ms=2.0, content_length=25)


def test_create_fetcher_can_disable_tls_verification(monkeypatch) -> None:
    captured_contexts: list[ssl.SSLContext | None] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def fake_urlopen(
        request: urllib.request.Request,
        *,
        timeout: float,
        context: ssl.SSLContext | None = None,
    ) -> FakeResponse:
        assert timeout == 1.0
        assert request.full_url == "https://pullbox.test/ping"
        captured_contexts.append(context)
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = create_fetcher(verify_tls=False)("https://pullbox.test/ping", 1.0)

    assert result.status_code == 200
    assert captured_contexts
    assert captured_contexts[0] is not None
    assert captured_contexts[0].verify_mode == ssl.CERT_NONE
    assert captured_contexts[0].check_hostname is False


def test_create_fetcher_applies_default_headers(monkeypatch) -> None:
    captured_headers: list[dict[str, str]] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def fake_urlopen(
        request: urllib.request.Request,
        *,
        timeout: float,
        context: ssl.SSLContext | None = None,
    ) -> FakeResponse:
        _ = timeout, context
        captured_headers.append(dict(request.header_items()))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    create_fetcher(headers={"HX-Request": "true"})("https://pullbox.test/htmx/series", 1.0)

    assert captured_headers[0]["Hx-request"] == "true"


def test_create_fetcher_reports_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        *,
        timeout: float,
        context: ssl.SSLContext | None = None,
    ) -> object:
        _ = request, timeout, context
        raise urllib.error.HTTPError(
            "https://pullbox.test/missing",
            404,
            "Not Found",
            hdrs=None,
            fp=io.BytesIO(b"missing"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = create_fetcher()("https://pullbox.test/missing", 1.0)

    assert result.status_code == 404
    assert result.content_length == len(b"missing")


def test_create_fetcher_rejects_non_http_urls() -> None:
    fetcher = create_fetcher()

    try:
        fetcher("file:///etc/passwd", 1.0)
    except ValueError as exc:
        assert "http or https" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("expected fetcher to reject non-http URL")


def test_login_and_create_fetcher_posts_login_and_reuses_cookie_opener(monkeypatch) -> None:
    opened_requests: list[tuple[str, bytes | None]] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    class FakeOpener:
        def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
            assert timeout == 2.0
            opened_requests.append((request.full_url, request.data))
            return FakeResponse()

    fake_opener = FakeOpener()

    def fake_build_opener(*handlers: object) -> FakeOpener:
        assert handlers
        return fake_opener

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    fetcher = login_and_create_fetcher(
        base_url="https://pullbox.test",
        login_url="/api/v1/auth/login",
        username="admin",
        password="TestPassword1!",
        timeout=2.0,
        verify_tls=False,
        headers={"HX-Request": "true"},
    )
    result = fetcher("https://pullbox.test/api/v1/series", 2.0)

    assert result.status_code == 200
    assert opened_requests[0][0] == "https://pullbox.test/api/v1/auth/login"
    assert opened_requests[0][1] == b'{"username":"admin","password":"TestPassword1!"}'
    assert opened_requests[1] == ("https://pullbox.test/api/v1/series", None)


def test_login_and_create_fetcher_rejects_failed_login(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 401

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"error": "bad credentials"}'

    class FakeOpener:
        def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
            _ = request, timeout
            return FakeResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: FakeOpener())

    with pytest.raises(RuntimeError, match="benchmark login failed"):
        login_and_create_fetcher(
            base_url="https://pullbox.test",
            login_url="/api/v1/auth/login",
            username="admin",
            password="wrong",
            timeout=2.0,
        )


def test_login_fetcher_reports_http_errors_from_authenticated_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLoginResponse:
        status = 200

        def __enter__(self) -> FakeLoginResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    class FakeOpener:
        def __init__(self) -> None:
            self.calls = 0

        def open(self, request: urllib.request.Request, timeout: float) -> FakeLoginResponse:
            _ = request, timeout
            self.calls += 1
            if self.calls == 1:
                return FakeLoginResponse()
            raise urllib.error.HTTPError(
                "https://pullbox.test/api/v1/series",
                500,
                "Server Error",
                hdrs=None,
                fp=io.BytesIO(b"boom"),
            )

    fake_opener = FakeOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: fake_opener)

    fetcher = login_and_create_fetcher(
        base_url="https://pullbox.test",
        login_url="/api/v1/auth/login",
        username="admin",
        password="TestPassword1!",
        timeout=2.0,
    )
    result = fetcher("https://pullbox.test/api/v1/series", 2.0)

    assert result.status_code == 500
    assert result.content_length == 4


def test_write_report_creates_parent_directories(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "baseline.json"

    write_report({"z": 1, "a": 2}, output_path)

    assert output_path.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "z": 1\n}\n'


def test_collect_context_handles_git_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline, "_run_git", lambda repo_root, *args: None)

    context = baseline.collect_context(tmp_path)

    assert context["repo_root"] == str(tmp_path.resolve())
    assert context["git_branch"] is None
    assert context["git_commit"] is None
    assert context["git_dirty"] is False


def test_run_git_returns_stripped_output_or_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        calls.append(args)
        _ = kwargs
        stdout = " feature/testing-coverage \n" if len(calls) == 1 else "\n"
        return baseline.subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    monkeypatch.setattr(baseline.subprocess, "run", fake_run)

    assert baseline._run_git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == (
        "feature/testing-coverage"
    )
    assert baseline._run_git(tmp_path, "status", "--short") is None


def test_main_writes_report_with_authenticated_fetcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "baseline.json"
    asset = tmp_path / "tailwind.css"
    asset.write_text("body{}\n", encoding="utf-8")
    login_calls: list[dict[str, object]] = []

    def fake_fetcher(url: str, timeout: float) -> FetchResult:
        return FetchResult(
            status_code=200,
            elapsed_ms=1.0,
            content_length=len(url) + int(timeout),
        )

    def fake_login_and_create_fetcher(**kwargs: object) -> baseline.Fetcher:
        login_calls.append(kwargs)
        return fake_fetcher

    monkeypatch.setattr(baseline, "login_and_create_fetcher", fake_login_and_create_fetcher)
    monkeypatch.setattr(
        baseline,
        "collect_context",
        lambda repo_root: {"repo_root": str(repo_root), "measurement_version": "test"},
    )

    exit_code = baseline.main(
        [
            "--repo-root",
            str(tmp_path),
            "--base-url",
            "https://pullbox.test",
            "--endpoint",
            "Ping=/ping",
            "--static-asset",
            f"Tailwind={asset}",
            "--samples",
            "1",
            "--timeout",
            "2.0",
            "--insecure",
            "--header",
            "HX-Request:true",
            "--username",
            "admin",
            "--password",
            "TestPassword1!",
            "--output",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert login_calls[0]["verify_tls"] is False
    assert login_calls[0]["headers"] == {"HX-Request": "true"}
    assert report["settings"]["login_enabled"] is True
    assert report["settings"]["headers"] == ["HX-Request"]
    assert report["http_endpoints"][0]["samples_completed"] == 1


def test_main_prints_report_when_output_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asset = tmp_path / "tailwind.css"
    asset.write_text("body{}\n", encoding="utf-8")
    monkeypatch.setattr(
        baseline,
        "create_fetcher",
        lambda **kwargs: (
            lambda url, timeout: FetchResult(
                status_code=200,
                elapsed_ms=1.0,
                content_length=len(url),
            )
        ),
    )
    monkeypatch.setattr(
        baseline,
        "collect_context",
        lambda repo_root: {"repo_root": str(repo_root), "measurement_version": "test"},
    )

    exit_code = baseline.main(
        [
            "--repo-root",
            str(tmp_path),
            "--skip-http",
            "--static-asset",
            f"Tailwind={asset}",
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert printed["http_endpoints"] == []
    assert printed["settings"]["login_enabled"] is False


def test_main_requires_username_and_password_together() -> None:
    with pytest.raises(SystemExit):
        baseline.main(["--username", "admin"])
