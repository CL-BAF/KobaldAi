"""Reproducible execution records.

A record is a plain JSON document written once per experiment run. It stores
what was asked, what was approved, exactly what ran (engine and dependency
versions, SI parameters, options, seed, sandbox limits), output hashes and the
independent verification verdict. Hostnames are never collected, and local
path prefixes (run directory, Python installation, home directory) are redacted
from every string before the record is written, including error tracebacks.
Raw ``stderr.log`` files inside the run directory are not redacted.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = [
    "FINAL_STATUSES",
    "RECORD_FILE",
    "RECORD_SCHEMA_VERSION",
    "atomic_write_bytes",
    "capture_environment",
    "package_versions",
    "verify_record",
    "write_record",
]

# v2: total experiment budget, requester, per-execution allowance/resource usage,
# richer sandbox limits, "running"/"interrupted" statuses.
RECORD_SCHEMA_VERSION = 2
RECORD_FILE = "record.json"
DIGEST_FILE = "record.sha256"
FINAL_STATUSES = frozenset(
    {
        "invalid",
        "denied",
        "awaiting_approval",
        "failed",
        "completed",
        "completed_verification_failed",
    }
)


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


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temporary file and ``os.replace`` so readers never see a partial file."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_record(run_dir: Path, record: dict[str, Any]) -> str:
    """Atomically write ``record.json`` then ``record.sha256``; return the digest.

    Bytes are written (not text) so Windows newline translation cannot change
    the hashed content. If the process dies between the two writes, the digest
    file is stale and :func:`verify_record` reports the mismatch.
    """
    data = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    atomic_write_bytes(run_dir / RECORD_FILE, data)
    digest = hashlib.sha256(data).hexdigest()
    atomic_write_bytes(run_dir / DIGEST_FILE, f"{digest}  {RECORD_FILE}\n".encode())
    return digest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_record(run_dir: Path) -> list[str]:
    """Independently re-check a run directory. Returns a list of problems (empty = OK)."""
    record_path, digest_path = run_dir / RECORD_FILE, run_dir / DIGEST_FILE
    if not record_path.is_file():
        return [f"{RECORD_FILE} is missing"]
    problems: list[str] = []
    if not digest_path.is_file():
        problems.append(f"{DIGEST_FILE} is missing")
    elif digest_path.read_text(encoding="utf-8").split()[0] != _sha256(record_path):
        problems.append(f"{RECORD_FILE} does not match {DIGEST_FILE}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [*problems, f"{RECORD_FILE} is not valid JSON"]
    status = record.get("status")
    if status not in FINAL_STATUSES:
        problems.append(f"record is incomplete (status {status!r})")
    expected = dict(record.get("artifacts", {}))
    for execution in record.get("executions", []):
        outputs = execution.get("outputs")
        if outputs:
            expected[outputs["table"]] = outputs["table_sha256"]
    for name, digest in sorted(expected.items()):
        artifact = run_dir / name
        if not artifact.is_file():
            problems.append(f"artifact {name} is missing")
        elif _sha256(artifact) != digest:
            problems.append(f"artifact {name} does not match its recorded hash")
    return problems
