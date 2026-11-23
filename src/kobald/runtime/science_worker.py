"""Worker executed inside the sandbox subprocess.

Protocol: the parent writes ``job.json`` into a fresh working directory and
runs ``python -I -m kobald.runtime.science_worker <workdir>``. The worker
writes ``outputs/table.csv`` and ``result.json``. It never contacts the parent
otherwise and never makes policy or verification decisions.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kobald.integrations.science.base import AdapterResult
from kobald.integrations.science.registry import ScienceEngineRegistry, default_registry
from kobald.research.hashing import float_array_sha256

__all__ = ["JOB_FILE", "RESULT_FILE", "TABLE_FILE", "execute_job", "main", "write_table"]

JOB_FILE = "job.json"
RESULT_FILE = "result.json"
TABLE_FILE = "outputs/table.csv"


def write_table(path: Path, result: AdapterResult) -> list[dict[str, Any]]:
    """Write columns as CSV with exact round-trip float formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(result.columns)
    columns = [result.columns[name] for name in names]
    rows = zip(*(column.values for column in columns), strict=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(",".join(f"{n} [{c.unit}]" for n, c in zip(names, columns, strict=True)))
        handle.write("\n")
        for row in rows:
            handle.write(",".join(repr(value) for value in row))
            handle.write("\n")
    return [
        {"name": n, "unit": c.unit, "length": len(c.values), "sha256": float_array_sha256(c.values)}
        for n, c in zip(names, columns, strict=True)
    ]


def execute_job(workdir: Path, registry: ScienceEngineRegistry | None = None) -> int:
    """Run the job in ``workdir``; always writes ``result.json``. Returns an exit code."""
    result_path = workdir / RESULT_FILE
    try:
        job = json.loads((workdir / JOB_FILE).read_text(encoding="utf-8"))
        adapter, _definition = (registry or default_registry()).resolve(job["engine"], job["task"])
        result = adapter.run(job["task"], job["parameters"], job["options"], job["seed"])
        columns = write_table(workdir / TABLE_FILE, result)
        payload: dict[str, Any] = {
            "status": "ok",
            "engine_version": result.engine_version,
            "table": TABLE_FILE,
            "columns": columns,
            "scalars": {k: {"value": v, "unit": u} for k, (v, u) in result.scalars.items()},
            "diagnostics": dict(result.diagnostics),
            "warnings": list(result.warnings),
        }
        code = 0
    except Exception as error:  # report every engine failure as structured data
        payload = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error)[:2000],
            "traceback": traceback.format_exc(limit=8)[-4000:],
        }
        code = 2
    result_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    return code


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2:
        print("usage: python -I -m kobald.runtime.science_worker <workdir>", file=sys.stderr)
        return 64
    return execute_job(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
