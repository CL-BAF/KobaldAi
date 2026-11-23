"""Resource-limited subprocess execution for scientific jobs.

Enforced on every platform:
  * separate interpreter process in isolated mode (``python -I``)
  * dedicated working directory as cwd, TEMP, HOME and config root
  * scrubbed environment (API keys and user variables are not inherited)
  * wall-clock limit measured from spawn until the whole process tree has been
    killed and reaped (overhead and termination count against the budget)
  * process-tree termination on timeout, completion and interruption
  * cap on bytes written to the working directory and on ``result.json`` size
  * single-threaded numerical libraries

Platform controllers:
  * Windows: a Job Object (kill-on-close, committed-memory cap, peak memory).
  * POSIX: a new session/process group (``killpg``) plus ``RLIMIT_AS`` and
    ``RLIMIT_CPU``. A descendant that calls ``setsid`` escapes the group.

NOT enforced anywhere: network isolation, filesystem confinement, or reduced
privileges. The worker runs with the invoking user's full rights and can read
anything that user can (including credentials). Every outcome records which
limits applied, so execution records never overstate isolation. Only Kobald's
own adapters run in the sandbox; untrusted code execution is not supported.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from kobald.research.spec import ResourceBudget
from kobald.runtime.science_worker import JOB_FILE, RESULT_FILE

__all__ = [
    "ExecutionBackend",
    "ProcessController",
    "SandboxLimits",
    "SandboxOutcome",
    "SandboxSetupError",
    "SandboxStatus",
    "SubprocessSandbox",
    "default_controller",
    "directory_size",
    "scrubbed_environment",
]

_MAX_RESULT_JSON_BYTES = 2_000_000
_TAIL_BYTES = 4000
_PASSTHROUGH_ENV = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "LANG", "LC_ALL")


class SandboxSetupError(RuntimeError):
    """Raised when process-tree or resource controls cannot be applied."""


class SandboxStatus(Enum):
    OK = "ok"
    ENGINE_ERROR = "engine_error"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    OUTPUT_LIMIT = "output_limit"
    SETUP_ERROR = "setup_error"


class ProcessController(Protocol):
    """Platform mechanism for process-tree control and memory limits."""

    @property
    def name(self) -> str: ...

    @property
    def memory_limit_kind(self) -> str | None: ...

    def popen_kwargs(self) -> dict[str, Any]: ...

    def attach(self, process: subprocess.Popen[bytes]) -> None: ...

    def kill_tree(self, process: subprocess.Popen[bytes]) -> None: ...

    def peak_memory_bytes(self) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    backend: str
    controller: str
    wall_time_s: float
    max_output_bytes: int
    memory_mb: int
    memory_limit_kind: str | None
    process_tree_controlled: bool
    network_isolated: bool
    filesystem_confined: bool
    privileges_reduced: bool
    environment_scrubbed: bool

    @property
    def memory_limit_enforced(self) -> bool:
        return self.memory_limit_kind is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "controller": self.controller,
            "wall_time_s": self.wall_time_s,
            "max_output_bytes": self.max_output_bytes,
            "memory_mb": self.memory_mb,
            "memory_limit_enforced": self.memory_limit_enforced,
            "memory_limit_kind": self.memory_limit_kind,
            "process_tree_controlled": self.process_tree_controlled,
            "network_isolated": self.network_isolated,
            "filesystem_confined": self.filesystem_confined,
            "privileges_reduced": self.privileges_reduced,
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
    peak_memory_bytes: int | None = None
    setup_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "returncode": self.returncode,
            "duration_s": self.duration_s,
            "stderr_tail": self.stderr_tail,
            "peak_memory_bytes": self.peak_memory_bytes,
            "setup_error": self.setup_error,
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
            "USERPROFILE": str(workdir),
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


if sys.platform == "win32":  # pragma: windows-only

    class _WindowsJobController:
        name = "windows-job-object"
        memory_limit_kind = "job_committed_memory"

        def __init__(self, memory_mb: int) -> None:
            from kobald.runtime.winjob import JobObjectError, WindowsJob

            try:
                self._job = WindowsJob(memory_mb * 1024 * 1024)
            except JobObjectError as error:
                raise SandboxSetupError(str(error)) from error

        def popen_kwargs(self) -> dict[str, Any]:
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

        def attach(self, process: subprocess.Popen[bytes]) -> None:
            from kobald.runtime.winjob import JobObjectError

            try:
                self._job.assign(int(process._handle))  # type: ignore[attr-defined]
            except JobObjectError as error:
                raise SandboxSetupError(str(error)) from error

        def kill_tree(self, process: subprocess.Popen[bytes]) -> None:
            self._job.terminate()
            process.kill()

        def peak_memory_bytes(self) -> int | None:
            return self._job.peak_memory_bytes()

        def close(self) -> None:
            self._job.close()


class _PosixGroupController:  # pragma: posix-only
    name = "posix-process-group"
    memory_limit_kind = "rlimit_address_space"

    def __init__(self, memory_mb: int, cpu_s: float) -> None:
        self._memory = memory_mb * 1024 * 1024
        self._cpu = int(cpu_s) + 1

    def popen_kwargs(self) -> dict[str, Any]:
        memory, cpu = self._memory, self._cpu

        def apply_limits() -> None:
            if sys.platform != "win32":
                import resource

                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))

        return {"start_new_session": True, "preexec_fn": apply_limits}

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        return None

    def kill_tree(self, process: subprocess.Popen[bytes]) -> None:
        if sys.platform != "win32":
            import signal

            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    def peak_memory_bytes(self) -> int | None:
        return None

    def close(self) -> None:
        return None


def default_controller(budget: ResourceBudget) -> ProcessController:
    if sys.platform == "win32":  # pragma: windows-only
        return _WindowsJobController(budget.memory_mb)
    return _PosixGroupController(budget.memory_mb, budget.wall_time_s)  # pragma: posix-only


ControllerFactory = Callable[[ResourceBudget], ProcessController]


class SubprocessSandbox:
    """Runs ``kobald.runtime.science_worker`` in a constrained child interpreter."""

    def __init__(
        self,
        python: str = sys.executable,
        controller_factory: ControllerFactory = default_controller,
    ) -> None:
        self._python = python
        self._controller_factory = controller_factory

    def execute(
        self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
    ) -> SandboxOutcome:
        workdir = workdir.resolve()  # the child's cwd is workdir, so pass an absolute path
        workdir.mkdir(parents=True, exist_ok=False)
        (workdir / JOB_FILE).write_text(json.dumps(job, allow_nan=False), encoding="utf-8")
        argv = [self._python, "-I", "-m", "kobald.runtime.science_worker", str(workdir)]
        return self._run(argv, workdir, budget)

    def _run(self, argv: Sequence[str], workdir: Path, budget: ResourceBudget) -> SandboxOutcome:
        """Spawn ``argv`` under the sandbox controls. Private: only ``execute`` and
        security tests may call it; no public path accepts an arbitrary command."""
        started = time.monotonic()
        returncode: int | None = None
        timed_out = False
        peak: int | None = None
        setup_error: str | None = None
        try:
            controller = self._controller_factory(budget)
        except SandboxSetupError as error:
            limits = self._limits(budget, None)
            return SandboxOutcome(
                SandboxStatus.SETUP_ERROR, None, 0.0, workdir, None, "", limits, None, str(error)
            )
        limits = self._limits(budget, controller)
        try:
            with (
                (workdir / "stdout.log").open("wb") as out,
                (workdir / "stderr.log").open("wb") as err,
            ):
                process = subprocess.Popen(
                    list(argv),
                    cwd=workdir,
                    env=scrubbed_environment(workdir),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    **controller.popen_kwargs(),
                )
                try:
                    controller.attach(process)
                    remaining = budget.wall_time_s - (time.monotonic() - started)
                    returncode = process.wait(timeout=max(remaining, 0.0))
                except subprocess.TimeoutExpired:
                    timed_out = True
                except SandboxSetupError as error:
                    setup_error = str(error)
                except BaseException:
                    controller.kill_tree(process)
                    process.wait()
                    raise
                finally:
                    # Always reap the whole tree, including after a normal exit,
                    # so no descendant outlives the execution.
                    controller.kill_tree(process)
                    if returncode is None:
                        process.wait()
                    peak = controller.peak_memory_bytes()
        finally:
            controller.close()
        duration = time.monotonic() - started

        def outcome(status: SandboxStatus, result: Mapping[str, Any] | None) -> SandboxOutcome:
            return SandboxOutcome(
                status,
                returncode,
                duration,
                workdir,
                result,
                _tail(workdir / "stderr.log"),
                limits,
                peak,
                setup_error,
            )

        if setup_error is not None:
            return outcome(SandboxStatus.SETUP_ERROR, None)
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

    def _limits(
        self, budget: ResourceBudget, controller: ProcessController | None
    ) -> SandboxLimits:
        return SandboxLimits(
            backend="local-subprocess",
            controller=controller.name if controller is not None else "none",
            wall_time_s=budget.wall_time_s,
            max_output_bytes=budget.max_output_bytes,
            memory_mb=budget.memory_mb,
            memory_limit_kind=controller.memory_limit_kind if controller is not None else None,
            process_tree_controlled=controller is not None,
            network_isolated=False,
            filesystem_confined=False,
            privileges_reduced=False,
            environment_scrubbed=True,
        )
