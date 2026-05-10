"""Conversão de escalares numpy/pandas para tipos nativos (JSON/SQL seguros)."""

from __future__ import annotations

from math import isfinite
from typing import Any


def plain_python(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, dict):
        return {k: plain_python(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [plain_python(v) for v in val]
    if isinstance(val, (str, bytes, bytearray, memoryview)):
        return val
    if hasattr(val, "item") and callable(getattr(val, "item", None)):
        try:
            return plain_python(val.item())
        except Exception:
            pass
    if isinstance(val, float) and not isfinite(val):
        return None
    return val
