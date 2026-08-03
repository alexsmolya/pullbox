"""Validated artifact-host capabilities declared by direct providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pullbox.models.direct_acquisition import DirectArtifactHostKind


def parse_artifact_host_kinds(raw_values: object) -> frozenset[DirectArtifactHostKind]:
    """Return only supported host identifiers from an untrusted manifest value."""
    if not isinstance(raw_values, (list, tuple, set, frozenset)):
        return frozenset()
    parsed: set[DirectArtifactHostKind] = set()
    for value in raw_values:
        if not isinstance(value, str):
            continue
        try:
            parsed.add(DirectArtifactHostKind(value))
        except ValueError:
            continue
    return frozenset(parsed)


def manifest_artifact_host_kinds(
    manifest_snapshot: Mapping[str, object] | object,
) -> frozenset[DirectArtifactHostKind]:
    """Read host capabilities from one persisted provider manifest."""
    if not isinstance(manifest_snapshot, Mapping):
        return frozenset()
    return parse_artifact_host_kinds(manifest_snapshot.get("artifact_host_patterns"))


def uses_internal_generic_https(manifest_snapshot: Mapping[str, object] | object) -> bool:
    """Return whether the provider exposes only its validated final HTTPS route."""
    return manifest_artifact_host_kinds(manifest_snapshot) == {DirectArtifactHostKind.GENERIC_HTTPS}


def visible_artifact_host_kinds(
    enabled_provider_patterns: Iterable[object],
) -> frozenset[DirectArtifactHostKind]:
    """Return configurable hosts only when an enabled provider has named mirrors."""
    declared: set[DirectArtifactHostKind] = set()
    for raw_patterns in enabled_provider_patterns:
        declared.update(parse_artifact_host_kinds(raw_patterns))
    if not declared.difference({DirectArtifactHostKind.GENERIC_HTTPS}):
        return frozenset()
    return frozenset(declared)
