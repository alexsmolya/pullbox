"""Release notification payload contracts."""

from __future__ import annotations

from pathlib import Path

from pullbox.release_discord_delivery import delivery_task
from pullbox.release_discord_notifications import (
    announcement_payload,
    changelog_payload,
    notification_channels,
)

CHANGELOG = """### Added

- Added one important capability.
- Added a second important capability.

### Fixed

- Fixed a frustrating edge case.
"""


def test_final_releases_always_send_a_changelog_notification() -> None:
    assert notification_channels("1.2.3") == ("changelog",)
    assert notification_channels("1.2.0") == ("changelog", "announcements")
    assert notification_channels("2.0.0") == ("changelog", "announcements")


def test_prereleases_never_send_public_notifications() -> None:
    assert notification_channels("1.2.0-rc.1") == ()


def test_delivery_tasks_are_stable_per_channel() -> None:
    assert delivery_task("changelog") == "pullbox-discord-changelog"
    assert delivery_task("announcements") == "pullbox-discord-announcements"


def test_release_workflow_only_posts_after_a_successful_reservation() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "steps.reserve-changelog.outcome == 'success'" in workflow
    assert "steps.reserve-announcement.outcome == 'success'" in workflow
    assert "--retry-all-errors" not in workflow


def test_changelog_payload_is_an_embed_with_mentions_disabled() -> None:
    payload = changelog_payload(
        "1.2.3", CHANGELOG, "https://github.com/pullboxapp/pullbox/releases/tag/v1.2.3"
    )

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["title"] == "Pullbox v1.2.3 changelog"
    assert "Added one important capability." in payload["embeds"][0]["description"]
    assert payload["embeds"][0]["url"].endswith("v1.2.3")


def test_announcement_payload_is_short_and_links_to_the_release() -> None:
    payload = announcement_payload(
        "1.2.0", CHANGELOG, "https://github.com/pullboxapp/pullbox/releases/tag/v1.2.0"
    )

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["title"] == "Pullbox v1.2.0 is out"
    assert "Added one important capability." in payload["embeds"][0]["description"]
    assert "Fixed a frustrating edge case." not in payload["embeds"][0]["description"]
    assert "Read the full release notes" in payload["embeds"][0]["description"]
