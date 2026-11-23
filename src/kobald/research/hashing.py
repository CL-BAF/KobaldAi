"""Deterministic content hashing for reproducibility records."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence
from pathlib import Path

__all__ = ["file_sha256", "float_array_sha256"]


def float_array_sha256(values: Sequence[float]) -> str:
    """SHA-256 of the values packed as little-endian IEEE-754 float64."""
    return hashlib.sha256(struct.pack(f"<{len(values)}d", *values)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
