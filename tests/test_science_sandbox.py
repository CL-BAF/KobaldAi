"""Sandbox worker protocol and subprocess execution limits."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from kobald.research.spec import ResourceBudget
from kobald.runtime import sandbox as sandbox_module
from kobald.runtime.sandbox import (
    SandboxStatus,
    SubprocessSandbox,
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
BUDGET = ResourceBudget(wall_time_s=60.0, memory_mb=512, max_output_bytes=5_000_000)


def _write_job(workdir: Path, job: dict[str, Any]) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / JOB_FILE).write_text(json.dumps(job), encoding="utf-8")


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


def test_environment_is_scrubbed(tmp_path: Path) -> None:
    source = {"PATH": "/bin", "SYSTEMROOT": "C:\\Windows", "OPENAI_API_KEY": "secret", "HOME": "/x"}
    env = scrubbed_environment(tmp_path, source)
    assert "OPENAI_API_KEY" not in env
    assert env["PATH"] == "/bin" and env["SYSTEMROOT"] == "C:\\Windows"
    assert env["HOME"] == str(tmp_path) and env["OMP_NUM_THREADS"] == "1"
    assert "PATH" in scrubbed_environment(tmp_path)


def test_subprocess_sandbox_runs_real_job(tmp_path: Path) -> None:
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)
    assert outcome.status is SandboxStatus.OK, outcome.stderr_tail
    assert outcome.returncode == 0 and outcome.result is not None
    assert outcome.workdir.is_absolute()
    limits = outcome.to_dict()["limits"]
    assert limits["environment_scrubbed"] is True
    assert limits["network_isolated"] is False  # never overstated


def test_relative_workdir_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    outcome = SubprocessSandbox().execute(JOB, Path("relative-run"), BUDGET)
    assert outcome.status is SandboxStatus.OK, outcome.stderr_tail


def test_engine_failure_is_reported(tmp_path: Path) -> None:
    outcome = SubprocessSandbox().execute({**JOB, "task": "nope"}, tmp_path / "run", BUDGET)
    assert outcome.status is SandboxStatus.ENGINE_ERROR
    assert outcome.result is not None and outcome.result["status"] == "error"


def test_wall_time_limit_kills_the_job(tmp_path: Path) -> None:
    budget = ResourceBudget(wall_time_s=0.001, memory_mb=512, max_output_bytes=5_000_000)
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", budget)
    assert outcome.status is SandboxStatus.TIMEOUT
    assert outcome.returncode is None and outcome.result is None


def test_output_limit_is_enforced(tmp_path: Path) -> None:
    budget = ResourceBudget(wall_time_s=60.0, memory_mb=512, max_output_bytes=100)
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", budget)
    assert outcome.status is SandboxStatus.OUTPUT_LIMIT


def test_existing_workdir_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    with pytest.raises(FileExistsError):
        SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)


def _fake_run(writer: Any, returncode: int = 0) -> Any:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        writer(Path(kwargs["cwd"]))
        return subprocess.CompletedProcess(command, returncode)

    return run


@pytest.mark.parametrize(
    ("writer", "returncode", "expected"),
    [
        (lambda d: None, 1, SandboxStatus.CRASHED),
        (lambda d: (d / RESULT_FILE).write_text("{not json"), 0, SandboxStatus.CRASHED),
        (lambda d: (d / RESULT_FILE).write_text(" " * 2_000_001), 0, SandboxStatus.CRASHED),
        (lambda d: (d / RESULT_FILE).write_text('{"status": "ok"}'), 3, SandboxStatus.ENGINE_ERROR),
        (lambda d: (d / RESULT_FILE).write_text('{"status": "?"}'), 0, SandboxStatus.ENGINE_ERROR),
    ],
    ids=["no-result", "bad-json", "oversized-result", "nonzero-exit", "unknown-status"],
)
def test_malformed_worker_output_is_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Any,
    returncode: int,
    expected: SandboxStatus,
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(writer, returncode))
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)
    assert outcome.status is expected
    assert outcome.stderr_tail == ""


def test_stderr_tail_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def writer(workdir: Path) -> None:
        (workdir / "stderr.log").write_text("x" * 10_000 + "END")

    monkeypatch.setattr(subprocess, "run", _fake_run(writer, 1))
    outcome = SubprocessSandbox().execute(JOB, tmp_path / "run", BUDGET)
    assert len(outcome.stderr_tail) == 4000 and outcome.stderr_tail.endswith("END")


def test_tail_of_missing_file_is_empty(tmp_path: Path) -> None:
    assert sandbox_module._tail(tmp_path / "missing.log") == ""


def test_directory_size_counts_nested_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_bytes(b"12345")
    (tmp_path / "g").write_bytes(b"12")
    assert directory_size(tmp_path) == 7


def test_limits_report_posix_memory_enforcement() -> None:
    assert SubprocessSandbox(posix=True).limits(BUDGET).memory_limit_enforced is True
    assert SubprocessSandbox(posix=False).limits(BUDGET).memory_limit_enforced is False
