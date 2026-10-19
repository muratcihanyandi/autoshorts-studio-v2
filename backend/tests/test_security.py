"""Token cipher (Fernet) unit tests."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.security import TokenCipher, TokenEncryptionError


def test_roundtrip() -> None:
    key = Fernet.generate_key().decode()
    cipher = TokenCipher(key)
    encrypted = cipher.encrypt("ya29.gizli-token")
    assert encrypted != "ya29.gizli-token"
    assert cipher.decrypt(encrypted) == "ya29.gizli-token"


def test_wrong_key_fails() -> None:
    encrypted = TokenCipher(Fernet.generate_key().decode()).encrypt("ya29.token")
    other = TokenCipher(Fernet.generate_key().decode())
    with pytest.raises(TokenEncryptionError):
        other.decrypt(encrypted)


def test_ciphertext_is_not_plaintext() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    token = "1//refresh-token"
    encrypted = cipher.encrypt(token)
    assert token not in encrypted
