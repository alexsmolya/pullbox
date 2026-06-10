"""Extended unit tests for the encryption module.

Covers encrypt/decrypt round-trip, plaintext passthrough, double-encrypt
prevention, is_encrypted detection, empty string handling, and invalid
token error handling.

Run:
    pytest tests/unit/test_encryption_extended.py -v
"""

from unittest.mock import patch

import pytest

from pullbox.core.encryption import (
    _ENC_PREFIX,
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
)


@pytest.fixture(autouse=True)
def _clear_fernet_cache() -> None:
    """Clear the LRU-cached Fernet instance between tests."""
    from pullbox.core.encryption import _get_fernet

    _get_fernet.cache_clear()


@pytest.fixture(autouse=True)
def _mock_config_provider() -> None:
    """Provide a deterministic secret key for all encryption tests."""
    from unittest.mock import MagicMock

    mock_provider = MagicMock()
    mock_provider.secret_key.return_value = "test-secret-key-for-encryption-tests"
    with patch("pullbox.core.config_file.get_config_provider", return_value=mock_provider):
        yield


class TestEncryptDecryptRoundtrip:
    """Encryption followed by decryption should return the original."""

    def test_basic_roundtrip(self) -> None:
        plaintext = "my-super-secret-api-key"
        encrypted = encrypt_secret(plaintext)
        assert encrypted.startswith(_ENC_PREFIX)
        assert decrypt_secret(encrypted) == plaintext

    def test_roundtrip_with_special_chars(self) -> None:
        plaintext = "p@$$w0rd!#%^&*()_+-=[]{}|;':\",./<>?"
        encrypted = encrypt_secret(plaintext)
        assert decrypt_secret(encrypted) == plaintext

    def test_roundtrip_unicode(self) -> None:
        plaintext = "密码-パスワード-пароль"
        encrypted = encrypt_secret(plaintext)
        assert decrypt_secret(encrypted) == plaintext

    def test_roundtrip_long_value(self) -> None:
        plaintext = "x" * 10_000
        encrypted = encrypt_secret(plaintext)
        assert decrypt_secret(encrypted) == plaintext


class TestEmptyStringPassthrough:
    """Empty strings should pass through unchanged."""

    def test_encrypt_empty_string(self) -> None:
        assert encrypt_secret("") == ""

    def test_decrypt_empty_string(self) -> None:
        assert decrypt_secret("") == ""


class TestPlaintextPassthrough:
    """Legacy unencrypted data should be returned as-is by decrypt."""

    def test_decrypt_plaintext_passthrough(self) -> None:
        assert decrypt_secret("old-plaintext-key") == "old-plaintext-key"

    def test_decrypt_plaintext_with_special_chars(self) -> None:
        assert decrypt_secret("abc123!@#") == "abc123!@#"


class TestDoubleEncryptPrevention:
    """Values already encrypted should not be double-encrypted."""

    def test_double_encrypt_returns_same(self) -> None:
        plaintext = "my-secret"
        first = encrypt_secret(plaintext)
        second = encrypt_secret(first)
        assert first == second

    def test_double_encrypt_still_decrypts(self) -> None:
        plaintext = "my-secret"
        first = encrypt_secret(plaintext)
        second = encrypt_secret(first)
        assert decrypt_secret(second) == plaintext


class TestIsEncrypted:
    """is_encrypted() should detect the enc: prefix."""

    def test_encrypted_value(self) -> None:
        encrypted = encrypt_secret("test")
        assert is_encrypted(encrypted) is True

    def test_plaintext_value(self) -> None:
        assert is_encrypted("plain-text") is False

    def test_empty_string(self) -> None:
        assert is_encrypted("") is False

    def test_none_value(self) -> None:
        assert is_encrypted(None) is False

    def test_prefix_only(self) -> None:
        assert is_encrypted("enc:") is True


class TestDecryptInvalidToken:
    """Decrypting with a wrong key should raise ValueError."""

    def test_invalid_fernet_token_raises(self) -> None:
        # Create a value with the prefix but garbage token data
        bad = f"{_ENC_PREFIX}not-a-valid-fernet-token"
        with pytest.raises(ValueError, match="Failed to decrypt secret"):
            decrypt_secret(bad)

    def test_wrong_key_raises(self) -> None:
        """Encrypt with one key, try to decrypt with another."""
        plaintext = "my-secret"
        encrypted = encrypt_secret(plaintext)

        # Clear cache and use a different key
        from pullbox.core.encryption import _get_fernet

        _get_fernet.cache_clear()
        with (
            patch(
                "pullbox.core.config_resolver.get_application_secret",
                return_value="completely-different-key",
            ),
            pytest.raises(ValueError, match="Failed to decrypt secret"),
        ):
            decrypt_secret(encrypted)


class TestGetFernetCaching:
    """_get_fernet() should be cached and return the same instance."""

    def test_fernet_cached(self) -> None:
        from pullbox.core.encryption import _get_fernet

        f1 = _get_fernet()
        f2 = _get_fernet()
        assert f1 is f2
