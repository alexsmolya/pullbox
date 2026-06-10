from __future__ import annotations

import ssl
import urllib.request
from typing import TYPE_CHECKING

from pullbox.performance.baseline import (
    EndpointSpec,
    FetchResult,
    build_baseline_report,
    create_fetcher,
    login_and_create_fetcher,
    measure_file_size,
    measure_http_endpoint,
    parse_endpoint_spec,
    parse_header_spec,
    summarize_numbers,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_endpoint_spec_supports_labelled_paths() -> None:
    spec = parse_endpoint_spec("Ping=/ping")

    assert spec == EndpointSpec(label="Ping", target="/ping")


def test_parse_endpoint_spec_uses_target_as_default_label() -> None:
    spec = parse_endpoint_spec("/api/v1/series")

    assert spec == EndpointSpec(label="/api/v1/series", target="/api/v1/series")


def test_parse_header_spec_supports_colon_separator() -> None:
    assert parse_header_spec("HX-Request:true") == ("HX-Request", "true")


def test_parse_header_spec_supports_equals_separator() -> None:
    assert parse_header_spec("X-API-Key=secret") == ("X-API-Key", "secret")


def test_summarize_numbers_reports_nearest_rank_p95() -> None:
    summary = summarize_numbers([10.0, 20.0, 30.0, 40.0])

    assert summary == {
        "samples": 4,
        "min": 10.0,
        "median": 25.0,
        "p95": 40.0,
        "max": 40.0,
    }


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


def test_measure_file_size_reports_raw_and_gzip_bytes(tmp_path: Path) -> None:
    target = tmp_path / "tailwind.css"
    target.write_text(".test { color: red; }\n" * 20, encoding="utf-8")

    measurement = measure_file_size("tailwind", target)

    assert measurement.label == "tailwind"
    assert measurement.path == str(target)
    assert measurement.raw_bytes == target.stat().st_size
    assert measurement.gzip_bytes > 0


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
