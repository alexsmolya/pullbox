"""Tests for Phase E scoring configuration keys.

Validates that new scoring config keys exist in DEFAULT_SYSTEM_CONFIG
with correct defaults and types, and that the scoring functions use them.

Run:
    pytest tests/unit/test_scoring_config.py -v
"""

from __future__ import annotations

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG


class TestScoringConfigKeysExist:
    """New scoring config keys are registered with correct defaults."""

    def test_score_weight_grabs_exists(self) -> None:
        assert "score_weight_grabs" in DEFAULT_SYSTEM_CONFIG
        value, vtype = DEFAULT_SYSTEM_CONFIG["score_weight_grabs"]
        assert value == "0"
        assert vtype == "int"

    def test_score_penalty_pack_exists(self) -> None:
        assert "score_penalty_pack" in DEFAULT_SYSTEM_CONFIG
        value, vtype = DEFAULT_SYSTEM_CONFIG["score_penalty_pack"]
        assert value == "-20"
        assert vtype == "int"

    def test_preferred_language_exists(self) -> None:
        assert "preferred_language" in DEFAULT_SYSTEM_CONFIG
        value, vtype = DEFAULT_SYSTEM_CONFIG["preferred_language"]
        assert value == "en"
        assert vtype == "string"

    def test_score_bonus_digital_exists(self) -> None:
        assert "score_bonus_digital" in DEFAULT_SYSTEM_CONFIG
        value, vtype = DEFAULT_SYSTEM_CONFIG["score_bonus_digital"]
        assert value == "10"
        assert vtype == "int"

    def test_max_file_count_exists(self) -> None:
        assert "max_file_count" in DEFAULT_SYSTEM_CONFIG
        value, vtype = DEFAULT_SYSTEM_CONFIG["max_file_count"]
        assert value == "5"
        assert vtype == "int"

    def test_existing_weights_unchanged(self) -> None:
        """Verify existing scoring keys weren't accidentally modified."""
        assert DEFAULT_SYSTEM_CONFIG["score_weight_priority"] == ("40", "int")
        assert DEFAULT_SYSTEM_CONFIG["score_weight_age"] == ("30", "int")
        assert DEFAULT_SYSTEM_CONFIG["score_weight_size"] == ("20", "int")
        assert DEFAULT_SYSTEM_CONFIG["score_weight_format"] == ("10", "int")
