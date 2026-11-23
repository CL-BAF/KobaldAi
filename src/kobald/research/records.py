"""Reproducible execution records.

A record is a plain JSON document written once per experiment run. It stores
what was asked, what was approved, exactly what ran (engine and dependency
versions, SI parameters, options, seed, sandbox limits), output hashes and the
independent verification verdict. Hostnames, usernames and absolute paths are
deliberately excluded.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = [
    "RECORD_FILE",
    "RECORD_SCHEMA_VERSION",
    "capture_environment",
    "package_versions",
    "write_record",
]

RECORD_SCHEMA_VERSION = 1
RECORD_FILE = "record.json"


def package_versions(names: Iterable[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def capture_environment(packages: Iterable[str]) -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "packages": package_versions(packages),
    }


def write_record(run_dir: Path, record: dict[str, Any]) -> str:
    """Write ``record.json`` and ``record.sha256``; return the record digest."""
    # Write bytes, not text: newline translation on Windows would change the hashed content.
    data = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    (run_dir / RECORD_FILE).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (run_dir / "record.sha256").write_text(f"{digest}  {RECORD_FILE}\n", encoding="utf-8")
    return digest
