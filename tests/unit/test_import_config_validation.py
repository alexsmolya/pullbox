"""Unit tests for import-related configuration validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pullbox.api.v1.config import update_config
from pullbox.core.exceptions import ValidationError
from pullbox.models.config import SystemConfig
from pullbox.schemas.config import ConfigUpdate


def _mock_request() -> MagicMock:
    request = MagicMock()
    request.client.host = "127.0.0.1"
    return request


class TestImportConfigValidation:
    """Validate import-specific media-management config interactions."""

    def test_torrent_import_strategy_default_is_standard(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert DEFAULT_SYSTEM_CONFIG["torrent_import_strategy"] == ("standard", "string")

    @pytest.mark.asyncio
    async def test_convert_on_import_rejects_hardlink_transfer(self, db_session) -> None:
        """Preferred-format conversion is incompatible with hardlink transfer."""
        with pytest.raises(ValidationError, match="Move or Copy"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(
                    values={
                        "post_processing_method": "hardlink",
                        "convert_to_preferred_format_on_import": "true",
                    }
                ),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_convert_on_import_persists_with_copy_transfer(self, db_session) -> None:
        """The import conversion setting is persisted when paired with a valid transfer mode."""
        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(
                values={
                    "post_processing_method": "copy",
                    "convert_to_preferred_format_on_import": "true",
                }
            ),
            _user=MagicMock(),
            session=db_session,
        )

        copy_method = await db_session.get(SystemConfig, "post_processing_method")
        convert_toggle = await db_session.get(SystemConfig, "convert_to_preferred_format_on_import")
        assert copy_method is not None
        assert convert_toggle is not None
        assert copy_method.value == "copy"
        assert convert_toggle.value == "true"

    @pytest.mark.asyncio
    async def test_torrent_import_strategy_accepts_standard_and_seed_safe(
        self,
        db_session,
    ) -> None:
        """Torrent import strategy accepts only the explicit supported values."""
        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(values={"torrent_import_strategy": "seed_safe"}),
            _user=MagicMock(),
            session=db_session,
        )
        strategy = await db_session.get(SystemConfig, "torrent_import_strategy")
        assert strategy is not None
        assert strategy.value == "seed_safe"

        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(values={"torrent_import_strategy": "standard"}),
            _user=MagicMock(),
            session=db_session,
        )
        assert strategy.value == "standard"

    @pytest.mark.asyncio
    async def test_torrent_import_strategy_rejects_unknown_value(self, db_session) -> None:
        """Unknown torrent import strategies return a useful validation error."""
        with pytest.raises(ValidationError, match="standard, seed_safe"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"torrent_import_strategy": "preserve"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_seed_safe_rejects_hardlink_with_content_mutation_settings(
        self,
        db_session,
    ) -> None:
        """Seed-safe mode cannot relax global mutation rules for non-torrent imports."""
        with pytest.raises(ValidationError, match="Move or Copy"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(
                    values={
                        "torrent_import_strategy": "seed_safe",
                        "post_processing_method": "hardlink",
                        "convert_to_preferred_format_on_import": "true",
                        "update_embedded_comicinfo_from_match_on_import": "true",
                    }
                ),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_process_completed_recovery_sweep_rejects_values_below_five_minutes(
        self,
        db_session,
    ) -> None:
        """The process-completed recovery sweep must stay at or above five minutes."""
        with pytest.raises(ValidationError, match="between 300 and 600 seconds"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"process_completed_interval_seconds": "299"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_process_completed_recovery_sweep_accepts_five_minutes(
        self,
        db_session,
    ) -> None:
        """The process-completed recovery sweep accepts the new five-minute floor."""
        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(values={"process_completed_interval_seconds": "300"}),
            _user=MagicMock(),
            session=db_session,
        )

        interval = await db_session.get(SystemConfig, "process_completed_interval_seconds")
        assert interval is not None
        assert interval.value == "300"

    @pytest.mark.asyncio
    async def test_library_permissions_accept_valid_modes(self, db_session) -> None:
        """Library permission settings accept explicit safe chmod modes."""
        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(
                values={
                    "library_permissions_enabled": "true",
                    "library_permissions_folder_mode": "0750",
                    "library_permissions_file_mode": "0640",
                }
            ),
            _user=MagicMock(),
            session=db_session,
        )

        folder_mode = await db_session.get(SystemConfig, "library_permissions_folder_mode")
        file_mode = await db_session.get(SystemConfig, "library_permissions_file_mode")
        assert folder_mode is not None
        assert file_mode is not None
        assert folder_mode.value == "0750"
        assert file_mode.value == "0640"

    @pytest.mark.asyncio
    async def test_library_permissions_reject_folder_without_owner_execute(
        self,
        db_session,
    ) -> None:
        """Folder modes must keep owner traversal rights."""
        with pytest.raises(ValidationError, match="folder modes must include owner execute"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"library_permissions_folder_mode": "0640"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_library_permissions_reject_file_execute_bits(self, db_session) -> None:
        """File modes reject execute bits unless a future feature explicitly enables them."""
        with pytest.raises(ValidationError, match="file modes must not include execute"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"library_permissions_file_mode": "0755"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_library_permissions_reject_unsupported_hardlink_behavior(
        self,
        db_session,
    ) -> None:
        """Hardlinks stay seed-safe by only supporting the skip behavior."""
        with pytest.raises(ValidationError, match="hardlink behavior must be one of: skip"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"library_permissions_hardlink_behavior": "apply"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_library_permissions_reject_unsupported_symlink_behavior(
        self,
        db_session,
    ) -> None:
        """Symlinks stay safe by only supporting the skip behavior."""
        with pytest.raises(ValidationError, match="symlink behavior must be one of: skip"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"library_permissions_symlink_behavior": "target"}),
                _user=MagicMock(),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_library_permissions_reject_user_facing_chown_config(self, db_session) -> None:
        """Ownership changes stay out of the v1 user-facing config surface."""
        with pytest.raises(ValidationError, match="Unknown configuration key"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"library_permissions_owner": "1000"}),
                _user=MagicMock(),
                session=db_session,
            )
