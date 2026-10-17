"""Symmetric encryption for OAuth tokens at rest (Fernet)."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionError(Exception):
    """The stored ciphertext could not be decrypted with the current key."""


class TokenCipher:
    """Encrypts/decrypts token strings with the configured Fernet key."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise TokenEncryptionError(
                "Saklı anahtarla çözülemeyen şifreli token."
            ) from exc
