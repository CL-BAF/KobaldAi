"""Resource-limited subprocess execution for scientific jobs.

Enforced on every platform:
  * separate interpreter process in isolated mode (``python -I``)
  * dedicated working directory as cwd, TEMP and config root
  * scrubbed environment (no API keys or user variables are inherited)
  * wall-clock timeout with process kill
  * cap on bytes written to the working directory and on ``result.json`` size
  * single-threaded numerical libraries (CPU-friendly, more reproducible)

Enforced only on POSIX: address-space and CPU-time rlimits.
**Not** enforced anywhere yet: network isolation and filesystem confinement
outside the working directory. Every outcome records which limits applied, so
execution records never overstate isolation. Stronger isolation (WSL2/Linux
containers, Windows Job Objects) is a planned :class:`ExecutionBackend`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from kobald.research.spec import ResourceBudget
from kobald.runtime.science_worker import JOB_FILE, RESULT_FILE

__all__ = [
    "ExecutionBackend",
    "SandboxLimits",
    "SandboxOutcome",
    "SandboxStatus",
    "SubprocessSandbox",
    "directory_size",
    "scrubbed_environment",
]

_MAX_RESULT_JSON_BYTES = 2_000_000
_TAIL_BYTES = 4000
_PASSTHROUGH_ENV = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "LANG", "LC_ALL")


class SandboxStatus(Enum):
    OK = "ok"
    ENGINE_ERROR = "engine_error"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    OUTPUT_LIMIT = "output_limit"


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    backend: str
    wall_time_s: float
    max_output_bytes: int
    memory_mb: int
    memory_limit_enforced: bool
    network_isolated: bool
    filesystem_confined: bool
    environment_scrubbed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "wall_time_s": self.wall_time_s,
            "max_output_bytes": self.max_output_bytes,
            "memory_mb": self.memory_mb,
            "memory_limit_enforced": self.memory_limit_enforced,
            "network_isolated": self.network_isolated,
            "filesystem_confined": self.filesystem_confined,
            "environment_scrubbed": self.environment_scrubbed,
        }


@dataclass(frozen=True, slots=True)
class SandboxOutcome:
    status: SandboxStatus
    returncode: int | None
    duration_s: float
    workdir: Path
    result: Mapping[str, Any] | None
    stderr_tail: str
    limits: SandboxLimits

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "returncode": self.returncode,
            "duration_s": self.duration_s,
            "stderr_tail": self.stderr_tail,
            "limits": self.limits.to_dict(),
        }


class ExecutionBackend(Protocol):
    def execute(
        self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
    ) -> SandboxOutcome: ...


def scrubbed_environment(workdir: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    env = {key: source[key] for key in _PASSTHROUGH_ENV if key in source}
    env.update(
        {
            "TEMP": str(workdir),
            "TMP": str(workdir),
            "TMPDIR": str(workdir),
            "HOME": str(workdir),
            "MPLCONFIGDIR": str(workdir / ".mpl"),
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    return env


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _tail(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - _TAIL_BYTES))
        return handle.read().decode("utf-8", errors="replace")


def _posix_limits(memory_mb: int, cpu_s: float) -> Callable[[], None]:  # pragma: no cover
    def apply() -> None:
        if sys.platform != "win32":
            import resource

            memory = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            cpu = int(cpu_s) + 1
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

    return apply


class SubprocessSandbox:
    """Runs ``kobald.runtime.science_worker`` in a constrained child interpreter."""

    def __init__(self, python: str = sys.executable, posix: bool = os.name == "posix") -> None:
        self._python = python
        self._posix = posix

    def limits(self, budget: ResourceBudget) -> SandboxLimits:
        return SandboxLimits(
            backend="local-subprocess",
            wall_time_s=budget.wall_time_s,
            max_output_bytes=budget.max_output_bytes,
            memory_mb=budget.memory_mb,
            memory_limit_enforced=self._posix,
            network_isolated=False,
            filesystem_confined=False,
            environment_scrubbed=True,
        )

    def execute(
        self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
    ) -> SandboxOutcome:
        workdir = workdir.resolve()  # the child's cwd is workdir, so pass an absolute path
        workdir.mkdir(parents=True, exist_ok=False)
        (workdir / JOB_FILE).write_text(json.dumps(job, allow_nan=False), encoding="utf-8")
        limits = self.limits(budget)
        command = [self._python, "-I", "-m", "kobald.runtime.science_worker", str(workdir)]
        extra: dict[str, Any] = {}
        if self._posix:  # pragma: no cover - exercised on POSIX CI only
            extra["preexec_fn"] = _posix_limits(budget.memory_mb, budget.wall_time_s)

        started = time.perf_counter()
        returncode: int | None
        with (workdir / "stdout.log").open("wb") as out, (workdir / "stderr.log").open("wb") as err:
            try:
                completed = subprocess.run(
                    command,
                    cwd=workdir,
                    env=scrubbed_environment(workdir),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    timeout=budget.wall_time_s,
                    check=False,
                    **extra,
                )
                returncode = completed.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                returncode = None
                timed_out = True
        duration = time.perf_counter() - started

        def outcome(status: SandboxStatus, result: Mapping[str, Any] | None) -> SandboxOutcome:
            return SandboxOutcome(
                status, returncode, duration, workdir, result, _tail(workdir / "stderr.log"), limits
            )

        if timed_out:
            return outcome(SandboxStatus.TIMEOUT, None)
        if directory_size(workdir) > budget.max_output_bytes:
            return outcome(SandboxStatus.OUTPUT_LIMIT, None)
        result_path = workdir / RESULT_FILE
        if not result_path.exists() or result_path.stat().st_size > _MAX_RESULT_JSON_BYTES:
            return outcome(SandboxStatus.CRASHED, None)
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return outcome(SandboxStatus.CRASHED, None)
        if returncode == 0 and result.get("status") == "ok":
            return outcome(SandboxStatus.OK, result)
        return outcome(SandboxStatus.ENGINE_ERROR, result)
