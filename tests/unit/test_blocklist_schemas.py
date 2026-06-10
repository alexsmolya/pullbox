"""
Unit tests for blocklist Pydantic schema validation.

Run:
    pytest tests/unit/test_blocklist_schemas.py -v
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pullbox.schemas.blocklist import BlocklistAddRequest, BlocklistBulkDeleteRequest


class TestBlocklistAddRequest:
    """Validation for BlocklistAddRequest."""

    def test_valid_with_all_fields(self) -> None:
        req = BlocklistAddRequest(
            release_title="Batman.018.2026",
            download_url="https://example.com/nzb/1",
            series_id=1,
            issue_id=42,
        )
        assert req.release_title == "Batman.018.2026"
        assert req.reason == "manual"  # default

    def test_valid_with_only_title(self) -> None:
        req = BlocklistAddRequest(release_title="Batman.018")
        assert req.release_title == "Batman.018"
        assert req.download_url is None
        assert req.series_id is None
        assert req.issue_id is None

    def test_missing_title_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistAddRequest()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("release_title",) for e in errors)

    def test_empty_title_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistAddRequest(release_title="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("release_title",) for e in errors)
        assert any("min_length" in str(e) or "too_short" in str(e) for e in errors)

    def test_title_over_500_chars_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistAddRequest(release_title="A" * 501)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("release_title",) for e in errors)

    def test_title_at_500_chars_passes(self) -> None:
        req = BlocklistAddRequest(release_title="A" * 500)
        assert len(req.release_title) == 500

    def test_reason_defaults_to_manual(self) -> None:
        req = BlocklistAddRequest(release_title="Test")
        assert req.reason == "manual"

    def test_invalid_reason_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistAddRequest(release_title="Test", reason="invalid")  # type: ignore[arg-type]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("reason",) for e in errors)

    def test_series_id_zero_fails(self) -> None:
        with pytest.raises(ValidationError):
            BlocklistAddRequest(release_title="Test", series_id=0)

    def test_series_id_negative_fails(self) -> None:
        with pytest.raises(ValidationError):
            BlocklistAddRequest(release_title="Test", series_id=-1)

    def test_issue_id_zero_fails(self) -> None:
        with pytest.raises(ValidationError):
            BlocklistAddRequest(release_title="Test", issue_id=0)


class TestBlocklistBulkDeleteRequest:
    """Validation for BlocklistBulkDeleteRequest."""

    def test_valid_with_one_id(self) -> None:
        req = BlocklistBulkDeleteRequest(ids=[1])
        assert req.ids == [1]

    def test_valid_with_100_ids(self) -> None:
        req = BlocklistBulkDeleteRequest(ids=list(range(1, 101)))
        assert len(req.ids) == 100

    def test_empty_ids_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistBulkDeleteRequest(ids=[])
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("ids",) for e in errors)
        assert any("min_length" in str(e) or "too_short" in str(e) for e in errors)

    def test_over_100_ids_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistBulkDeleteRequest(ids=list(range(1, 102)))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("ids",) for e in errors)

    def test_missing_ids_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BlocklistBulkDeleteRequest()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("ids",) for e in errors)
