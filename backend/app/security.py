"""Symmetric encryption for OAuth tokens at rest (Fernet)."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionError(Exception):
    """The stored ciphertext could not be decrypted with the current key."""


class TokenCipher:
    """Encrypts/decrypts token strings with the configured Fernet key."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            # Bozuk anahtar (örn. ortam değişkeninde geçersiz değer) servis
            # katmanında yakalanıp 503'e çevrilmeli; ham ValueError 500 olur.
            raise TokenEncryptionError(
                "Token şifreleme anahtarı geçerli bir Fernet anahtarı değil "
                "(32 bayt urlsafe base64 bekleniyor)."
            ) from exc

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise TokenEncryptionError(
                "Saklı anahtarla çözülemeyen şifreli token."
            ) from exc
