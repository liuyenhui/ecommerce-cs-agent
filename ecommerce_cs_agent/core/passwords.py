from __future__ import annotations

from typing import Any


def password_matches(email: Any, password: Any, expected_email: str, stored_hash: str) -> bool:
    if email != expected_email or not isinstance(password, str):
        return False
    if stored_hash.startswith("plain:"):
        return password == stored_hash.removeprefix("plain:")
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return _bcrypt_matches(password, stored_hash)
    return False


def _bcrypt_matches(password: str, stored_hash: str) -> bool:
    try:
        import bcrypt
    except ImportError:
        return False
    try:
        return bool(bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")))
    except ValueError:
        return False
