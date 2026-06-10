"""Typed search evaluation option payloads shared across services and tasks."""

from __future__ import annotations

from typing import TypedDict


class SearchEvalKwargs(TypedDict, total=False):
    """Keyword arguments accepted by search evaluation helpers."""

    ignore_words: list[str]
    score_weights: tuple[float, float, float, float]
    confidence_blend: float
    fuzzy_high_threshold: float
    fuzzy_low_threshold: float
    year_tolerance: int
    min_score: float
    min_size_mb: int
    max_size_mb: int
    preferred_format: str
    seeder_tiers: tuple[int, int, int]
    warn_issue_mb: int
    warn_collection_mb: int
    grabs_weight: int
    pack_penalty: int
    preferred_language: str
    digital_bonus: int
    max_file_count: int


class ValidatorKwargs(TypedDict, total=False):
    """Subset of evaluation kwargs used to configure the release validator."""

    ignore_words: list[str]
    fuzzy_high_threshold: float
    fuzzy_low_threshold: float
    year_tolerance: int
    warn_issue_mb: int
    warn_collection_mb: int
