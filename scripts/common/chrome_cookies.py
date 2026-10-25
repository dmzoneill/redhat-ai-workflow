"""Read cookies from a Chrome/Chromium profile on Linux.

Small in-repo replacement for ``pycookiecheat.chrome_cookies``. pycookiecheat
pins ``cryptography`` to an old, vulnerable release, so this module implements
the same Linux decryption using the patched ``cryptography`` package.

Chrome on Linux encrypts cookie values with AES-128-CBC. The key is derived
with PBKDF2-HMAC-SHA1 (salt ``saltysalt``, 1 iteration) from either the
"Chrome Safe Storage" secret in the desktop keyring (``v11`` values) or the
fixed password ``peanuts`` (``v10`` values). Since cookie DB schema 24 the
plaintext is prefixed with the SHA-256 of the cookie's host, which is removed.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT = b"saltysalt"
IV = b" " * 16
KEY_LENGTH = 16
DEFAULT_PASSWORD = b"peanuts"

logger = logging.getLogger(__name__)
HOST_HASH_DB_VERSION = 24


def derive_key(password: bytes) -> bytes:
    """Derive the AES key Chrome uses on Linux from a keyring password."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=KEY_LENGTH, salt=SALT, iterations=1)
    return kdf.derive(password)


def keyring_password(browser: str = "chrome") -> bytes:
    """Return the "<Browser> Safe Storage" secret, or Chrome's fallback password."""
    application = "chromium" if browser == "chromium" else "chrome"
    try:
        import secretstorage
    except ImportError:
        logger.debug("secretstorage not installed; using Chrome's default password")
        return DEFAULT_PASSWORD
    try:
        with secretstorage.dbus_init() as connection:
            collection = secretstorage.get_default_collection(connection)
            if collection.is_locked():
                collection.unlock()
            for item in collection.get_all_items():
                if item.get_attributes().get("application") == application:
                    return item.get_secret()
    except (OSError, secretstorage.exceptions.SecretStorageException) as exc:
        logger.debug("No desktop keyring available (%s); using Chrome's default password", exc)
    return DEFAULT_PASSWORD


def decrypt_value(encrypted: bytes, keys: dict[bytes, bytes], strip_host_hash: bool) -> str:
    """Decrypt one ``encrypted_value`` blob from the Cookies database."""
    prefix = encrypted[:3]
    if prefix not in keys:
        return encrypted.decode("utf-8", errors="replace")
    decryptor = Cipher(algorithms.AES(keys[prefix]), modes.CBC(IV)).decryptor()
    padded = decryptor.update(encrypted[3:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    if strip_host_hash:
        plain = plain[32:]
    return plain.decode("utf-8")


def _host_keys(hostname: str) -> list[str]:
    """Cookie host_key values that apply to ``hostname`` (host and parent domains)."""
    parts = hostname.split(".")
    keys = [hostname]
    for index in range(len(parts) - 1):
        keys.append("." + ".".join(parts[index:]))
    return keys


def chrome_cookies(
    url: str, cookie_file: str, browser: str = "chrome", password: bytes | None = None
) -> dict[str, str]:
    """Return ``{name: value}`` for cookies Chrome would send to ``url``."""
    hostname = urlparse(url).hostname or ""
    keys = {
        b"v10": derive_key(DEFAULT_PASSWORD),
        b"v11": derive_key(password if password is not None else keyring_password(browser)),
    }
    with tempfile.TemporaryDirectory() as tmp:
        # Copy so a running browser's lock on the database does not block us.
        db_copy = Path(tmp) / "Cookies"
        shutil.copyfile(cookie_file, db_copy)
        connection = sqlite3.connect(db_copy)
        try:
            row = connection.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
            strip_host_hash = bool(row) and int(row[0]) >= HOST_HASH_DB_VERSION
            host_keys = _host_keys(hostname)
            placeholders = ",".join("?" for _ in host_keys)
            rows = connection.execute(
                f"SELECT name, value, encrypted_value FROM cookies WHERE host_key IN ({placeholders})",
                host_keys,
            ).fetchall()
        finally:
            connection.close()
    cookies = {}
    for name, value, encrypted in rows:
        cookies[name] = value if value else decrypt_value(encrypted, keys, strip_host_hash)
    return cookies
