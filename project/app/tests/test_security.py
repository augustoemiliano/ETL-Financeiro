from __future__ import annotations

from app.core.security import hash_password, verify_password


def test_password_roundtrip() -> None:
    hashed = hash_password("senha-forte-123")
    assert verify_password("senha-forte-123", hashed) is True
    assert verify_password("outra", hashed) is False
