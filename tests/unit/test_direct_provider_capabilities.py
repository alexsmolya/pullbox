"""Direct-provider artifact-host capability contracts."""

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.services.direct_provider_capabilities import (
    manifest_artifact_host_kinds,
    uses_internal_generic_https,
    visible_artifact_host_kinds,
)


def test_generic_only_provider_uses_hidden_internal_transport() -> None:
    manifest = {"artifact_host_patterns": ["generic_https"]}

    assert uses_internal_generic_https(manifest) is True
    assert visible_artifact_host_kinds([manifest["artifact_host_patterns"]]) == frozenset()


def test_named_host_provider_keeps_generic_https_rankable() -> None:
    patterns = ["generic_https", "pixeldrain", "unsupported_host"]

    assert uses_internal_generic_https({"artifact_host_patterns": patterns}) is False
    assert visible_artifact_host_kinds([patterns]) == {
        DirectArtifactHostKind.GENERIC_HTTPS,
        DirectArtifactHostKind.PIXELDRAIN,
    }


def test_manifest_host_parser_ignores_malformed_capabilities() -> None:
    assert manifest_artifact_host_kinds({"artifact_host_patterns": "pixeldrain"}) == frozenset()
    assert manifest_artifact_host_kinds({"artifact_host_patterns": [None, 1]}) == frozenset()
