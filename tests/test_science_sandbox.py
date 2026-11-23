"""Sandbox worker protocol, limits, process-tree control and boundary audit.

The audit tests probe what the sandbox actually enforces using real child
processes, touching only localhost and ``tmp_path``. Tests named ``*_gap`` assert
a boundary that is NOT enforced, so a future hardening change must update them.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from kobald.research.spec import ResourceBudget
from kobald.runtime.sandbox import (
    SandboxOutcome,
    SandboxSetupError,
    SandboxStatus,
    SubprocessSandbox,
    default_controller,
    directory_size,
    scrubbed_environment,
)
from kobald.runtime.science_worker import JOB_FILE, RESULT_FILE, execute_job, main

JOB: dict[str, Any] = {
    "engine": "scipy",
    "task": "damped_harmonic_oscillator",
    "parameters": {
        "mass": 1.0,
        "stiffness": 1.0,
        "damping": 0.1,
        "initial_displacement": 1.0,
        "initial_velocity": 0.0,
        "duration": 1.0,
    },
    "options": {"method": "DOP853", "rtol": 1e-9, "atol": 1e-12, "n_samples": 11},
    "seed": None,
}
BUDGET = ResourceBudget(wall_time_s=60.0, memory_mb=1024, max_output_bytes=5_000_000)
WINDOWS = sys.platform == "win32"


def _write_job(workdir: Path, job: dict[str, Any]) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / JOB_FILE).write_text(json.dumps(job), encoding="utf-8")


def _probe(tmp_path: Path, code: str, budget: ResourceBudget = BUDGET, **kw: Any) -> SandboxOutcome:
    """Run a probe script under the sandbox controls via the private test seam."""
    workdir = tmp_path / "probe"
    workdir.mkdir()
    sandbox = SubprocessSandbox(**kw)
    return sandbox._run([sys.executable, "-I", "-c", code], workdir, budget)


# --- worker protocol -----------------------------------------------------------------


def test_worker_writes_table_and_hashes_in_process(tmp_path: Path) -> None:
    _write_job(tmp_path, JOB)
    assert execute_job(tmp_path) == 0
    result = json.loads((tmp_path / RESULT_FILE).read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert [c["name"] for c in result["columns"]] == ["time", "displacement", "velocity"]
    assert all(len(c["sha256"]) == 64 and c["length"] == 11 for c in result["columns"])
    header = (tmp_path / result["table"]).read_text(encoding="utf-8").splitlines()[0]
    assert header == "time [s],displacement [m],velocity [m/s]"


def test_worker_reports_engine_errors_as_data(tmp_path: Path) -> None:
    _write_job(tmp_path, {**JOB, "engine": "rdkit"})
    assert execute_job(tmp_path) == 2
    result = json.loads((tmp_path / RESULT_FILE).read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert result["error_type"] == "UnknownEngineTaskError"


def test_worker_main_validates_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["worker"]) == 64
    assert "usage" in capsys.readouterr().err
    _write_job(tmp_path, JOB)
    assert main(["worker", str(tmp_path)]) == 0


def test_resource_usage_parses_proc_status(tmp_path: Path) -> None:
    from kobald.runtime.science_worker import resource_usage

    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t  412345 kB\nVmHWM:\t   98765 kB\nThreads:\t1\n")
    assert resource_usage(status) == {"vmpeak_kb": 412345, "vmhwm_kb": 98765}
    assert resource_usage(tmp_path / "missing") == {}


def test_environment_is_scrubbed_in_process(tmp_path: Path) -> None:
    source = {"PATH": "/bin", "SYSTEMROOT": "C:\\Windows", "OPENAI_API_KEY": "secret", "HOME": "/x"}
    env = scrubbed_environment(tmp_path, source)
    assert "OPENAI_API_KEY" not in env
    assert env["PATH"] == "/bin" and env["SYSTEMROOT"] == "C:\\Windows"
    assert env["HOME"] == str(tmp_path) and env["OMP_NUM_THREADS"] == "1"
    assert "PATH" in scrubbed_environment(tmp_path)


def test_directory_size_counts_nested_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_bytes(b"12345")
    (tmp_path / "g").write_bytes(b"12")
    assert directory_size(tmp_path) == 7


# --- real executions ----------------------------------------------------------------


def test_subprocess_sandbox_runs_real_job(tmp_path: Path) -> None:
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)
    assert outcome.status is SandboxStatus.OK, outcome.stderr_tail
    assert outcome.returncode == 0 and outcome.result is not None
    assert outcome.workdir.is_absolute()
    limits = outcome.to_dict()["limits"]
    assert limits["process_tree_controlled"] is True
    assert limits["memory_limit_enforced"] is True
    assert limits["memory_limit_kind"] == (
        "job_committed_memory" if WINDOWS else "rlimit_address_space"
    )
    # Never overstated:
    assert limits["network_isolated"] is False
    assert limits["filesystem_confined"] is False
    assert limits["privileges_reduced"] is False
    if WINDOWS:
        assert outcome.peak_memory_bytes is not None and outcome.peak_memory_bytes > 10 * 2**20


def test_relative_workdir_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    outcome = SubprocessSandbox().execute(JOB, Path("relative-run"), BUDGET)
    assert outcome.status is SandboxStatus.OK, outcome.stderr_tail


def test_engine_failure_is_reported(tmp_path: Path) -> None:
    outcome = SubprocessSandbox().execute({**JOB, "task": "nope"}, tmp_path / "run", BUDGET)
    assert outcome.status is SandboxStatus.ENGINE_ERROR
    assert outcome.result is not None and outcome.result["status"] == "error"


def test_wall_time_counts_from_spawn_and_includes_termination(tmp_path: Path) -> None:
    budget = ResourceBudget(wall_time_s=1.5, memory_mb=1024, max_output_bytes=10**6)
    started = time.monotonic()
    outcome = _probe(tmp_path, "import time; time.sleep(60)", budget)
    elapsed = time.monotonic() - started
    assert outcome.status is SandboxStatus.TIMEOUT and outcome.result is None
    # Windows timers have ~15.6 ms granularity, so allow a small margin below 1.5 s.
    assert 1.5 - 0.05 <= outcome.duration_s <= elapsed < 15


def test_output_limit_is_enforced(tmp_path: Path) -> None:
    budget = ResourceBudget(wall_time_s=60.0, memory_mb=1024, max_output_bytes=100)
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", budget)
    assert outcome.status is SandboxStatus.OUTPUT_LIMIT


def test_existing_workdir_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    with pytest.raises(FileExistsError):
        SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("import sys; sys.exit(1)", SandboxStatus.CRASHED),
        ("open('result.json','w').write('{not json')", SandboxStatus.CRASHED),
        ("open('result.json','w').write(' ' * 2_000_001)", SandboxStatus.CRASHED),
        (
            "import sys; open('result.json','w').write('{\"status\": \"ok\"}'); sys.exit(3)",
            SandboxStatus.ENGINE_ERROR,
        ),
        ("open('result.json','w').write('{\"status\": \"?\"}')", SandboxStatus.ENGINE_ERROR),
    ],
    ids=["no-result", "bad-json", "oversized-result", "nonzero-exit", "unknown-status"],
)
def test_malformed_worker_output_is_classified(
    tmp_path: Path, code: str, expected: SandboxStatus
) -> None:
    assert _probe(tmp_path, code).status is expected


def test_stderr_tail_is_bounded(tmp_path: Path) -> None:
    outcome = _probe(tmp_path, "import sys; sys.stderr.write('x' * 10000 + 'END'); sys.exit(1)")
    assert len(outcome.stderr_tail) == 4000 and outcome.stderr_tail.endswith("END")


# --- controller decisions (cross-platform, with fakes) -------------------------------


class FakeController:
    name = "fake"
    memory_limit_kind = None

    def __init__(self, attach_error: BaseException | None = None) -> None:
        self.attach_error = attach_error
        self.killed = 0
        self.closed = False

    def popen_kwargs(self) -> dict[str, Any]:
        return {}

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        if self.attach_error is not None:
            raise self.attach_error

    def kill_tree(self, process: subprocess.Popen[bytes]) -> None:
        self.killed += 1
        process.kill()

    def peak_memory_bytes(self) -> int | None:
        return None

    def close(self) -> None:
        self.closed = True


def _factory(controller: FakeController) -> Callable[[ResourceBudget], FakeController]:
    return lambda budget: controller


def test_controller_creation_failure_fails_closed_without_spawning(tmp_path: Path) -> None:
    def broken(budget: ResourceBudget) -> FakeController:
        raise SandboxSetupError("job objects unavailable")

    outcome = _probe(tmp_path, "open('spawned','w').close()", controller_factory=broken)
    assert outcome.status is SandboxStatus.SETUP_ERROR
    assert outcome.setup_error == "job objects unavailable"
    assert outcome.limits.process_tree_controlled is False
    assert not (outcome.workdir / "spawned").exists()


def test_attach_failure_kills_the_child_and_fails_closed(tmp_path: Path) -> None:
    controller = FakeController(SandboxSetupError("assign failed"))
    outcome = _probe(
        tmp_path, "import time; time.sleep(60)", controller_factory=_factory(controller)
    )
    assert outcome.status is SandboxStatus.SETUP_ERROR
    assert outcome.setup_error == "assign failed"
    assert controller.killed >= 1 and controller.closed
    assert outcome.duration_s < 30


def test_interrupt_kills_the_tree_and_propagates(tmp_path: Path) -> None:
    controller = FakeController(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _probe(tmp_path, "import time; time.sleep(60)", controller_factory=_factory(controller))
    assert controller.killed >= 1 and controller.closed


def test_default_controller_matches_platform() -> None:
    controller = default_controller(BUDGET)
    try:
        assert controller.name == ("windows-job-object" if WINDOWS else "posix-process-group")
    finally:
        controller.close()


# --- boundary audit (real processes; localhost and tmp_path only) --------------------

_GRANDCHILD = (
    "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('.')\n    time.sleep(0.1)\n"
)


def _spawner(heartbeat: Path, then: str) -> str:
    return (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {_GRANDCHILD!r}, {str(heartbeat)!r}])\n"
        "time.sleep(1.0)\n"
        f"{then}\n"
    )


def _assert_heartbeat_stopped(heartbeat: Path) -> None:
    assert heartbeat.exists(), "grandchild never started"
    time.sleep(0.5)
    before = heartbeat.stat().st_size
    time.sleep(1.0)
    assert heartbeat.stat().st_size == before, "grandchild escaped the sandbox"


def test_grandchild_is_killed_on_timeout(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    budget = ResourceBudget(wall_time_s=4.0, memory_mb=1024, max_output_bytes=10**6)
    outcome = _probe(tmp_path, _spawner(heartbeat, "time.sleep(60)"), budget)
    assert outcome.status is SandboxStatus.TIMEOUT
    _assert_heartbeat_stopped(heartbeat)


def test_grandchild_is_killed_after_normal_exit(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    outcome = _probe(tmp_path, _spawner(heartbeat, "pass"))
    assert outcome.returncode == 0
    _assert_heartbeat_stopped(heartbeat)


def test_memory_limit_stops_large_allocations(tmp_path: Path) -> None:
    budget = ResourceBudget(wall_time_s=60.0, memory_mb=256, max_output_bytes=10**6)
    outcome = _probe(tmp_path, "b = bytearray(600 * 2**20)", budget)
    assert outcome.returncode not in (0, None)
    assert "MemoryError" in outcome.stderr_tail


def test_environment_secrets_do_not_reach_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOBALD_TEST_SECRET_TOKEN", "do-not-leak")
    outcome = _probe(tmp_path, "import os, json; print(json.dumps(dict(os.environ)))")
    env = json.loads((outcome.workdir / "stdout.log").read_text(encoding="utf-8"))
    assert "KOBALD_TEST_SECRET_TOKEN" not in env
    assert "do-not-leak" not in json.dumps(env)


def test_network_isolation_gap_localhost_is_reachable(tmp_path: Path) -> None:
    """GAP: the child can open network connections (verified on localhost only)."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(30)
        port = server.getsockname()[1]
        code = (
            f"import socket\ns = socket.create_connection(('127.0.0.1', {port}))\ns.sendall(b'x')\n"
        )
        outcome = _probe(tmp_path, code)
        connection, _ = server.accept()
        with connection:
            assert connection.recv(1) == b"x"
    assert outcome.returncode == 0
    assert outcome.limits.network_isolated is False


def test_filesystem_confinement_gap_outside_paths_are_accessible(tmp_path: Path) -> None:
    """GAP: the child can read and write outside its working directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("user data")
    code = (
        f"data = open({str(outside / 'secret.txt')!r}).read()\n"
        f"open({str(outside / 'written.txt')!r}, 'w').write(data)\n"
    )
    outcome = _probe(tmp_path, code)
    assert outcome.returncode == 0
    assert (outside / "written.txt").read_text() == "user data"
    assert outcome.limits.filesystem_confined is False


def test_tail_of_missing_file_is_empty(tmp_path: Path) -> None:
    from kobald.runtime.sandbox import _tail

    assert _tail(tmp_path / "missing.log") == ""
