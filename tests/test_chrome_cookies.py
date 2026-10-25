"""Tests for the in-repo Chrome cookie reader (replacement for pycookiecheat)."""

import hashlib
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scripts.common import chrome_cookies as cc


def _encrypt(plain: bytes, password: bytes, prefix: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    encryptor = Cipher(
        algorithms.AES(cc.derive_key(password)), modes.CBC(cc.IV)
    ).encryptor()
    return prefix + encryptor.update(padded) + encryptor.finalize()


def _make_db(path: Path, version: int, rows: list[tuple[str, str, str, bytes]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    connection.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
    columns = "host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB"
    connection.execute(f"CREATE TABLE cookies ({columns})")
    connection.executemany("INSERT INTO cookies VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def test_derive_key_matches_known_chrome_linux_key():
    """Key derived from 'peanuts' matches Chrome's documented Linux key."""
    # Well-known AES key for Chrome's fallback password on Linux.
    assert cc.derive_key(b"peanuts").hex() == "fd621fe5a2b402539dfa147ca9272778"


def test_v11_cookie_with_host_hash(tmp_path):
    """v11 values decrypt with the keyring key and drop the host hash."""
    host = ".slack.com"
    plain = hashlib.sha256(host.encode()).digest() + b"xoxd-secret%2Fvalue"
    db = tmp_path / "Cookies"
    _make_db(
        db,
        24,
        [
            (host, "d", "", _encrypt(plain, b"keyring-pw", b"v11")),
            (".example.com", "other", "x", b""),
        ],
    )
    result = cc.chrome_cookies(
        "https://app.slack.com", cookie_file=str(db), password=b"keyring-pw"
    )
    assert result == {"d": "xoxd-secret%2Fvalue"}


def test_v10_cookie_and_plain_value_without_host_hash(tmp_path):
    """v10 values use the fallback key; plain values pass through."""
    db = tmp_path / "Cookies"
    _make_db(
        db,
        18,
        [
            ("app.slack.com", "a", "", _encrypt(b"alpha", b"peanuts", b"v10")),
            (".slack.com", "b", "plain", b""),
        ],
    )
    result = cc.chrome_cookies(
        "https://app.slack.com/client", cookie_file=str(db), password=b"unused"
    )
    assert result == {"a": "alpha", "b": "plain"}


def test_host_keys_include_parent_domains():
    """Cookies set on parent domains apply to the host."""
    assert cc.host_keys_for("app.slack.com") == [
        "app.slack.com",
        ".app.slack.com",
        ".slack.com",
    ]
