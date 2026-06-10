"""Mass-convert pipeline safety behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.mass_convert_pipeline import MassConvertPipelineExecutor

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_mass_convert_classifies_pillow_resource_safety_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Oversized.pdf"
    source.write_bytes(b"%PDF-1.7 placeholder")

    def fake_convert_sync(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(
            "Archive worker failed during convert: DecompressionBombError: "
            "Image size exceeds limit of 178956970 pixels"
        )

    monkeypatch.setattr(
        "pullbox.utilities.executors.file_converter._convert_sync",
        fake_convert_sync,
    )

    processed = MassConvertPipelineExecutor().process_item(
        {"id": "item-1", "file_path": str(source), "operation": "convert"},
        {"steps": [1]},
    )

    assert processed.result == ItemResult.FAILED
    assert processed.before_state["path"] == str(source)
    assert processed.before_state["safety_block"]["kind"] == "pillow_decompression_bomb"
    assert "safe image processing limit" in (processed.error_message or "")
    assert any("safety review" in message for _level, message, _extra in processed.log_entries)
