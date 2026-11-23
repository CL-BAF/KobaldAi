"""End-to-end experiment orchestration, records, reports and the operator CLI."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kobald.integrations.science import default_registry
from kobald.policy.science import (
    Principal,
    PrincipalKind,
    ScientificExecutionGate,
    ScientificExecutionPolicy,
)
from kobald.providers.base import Message, ModelIdentity, ModelProvider, ModelReply
from kobald.research.records import package_versions
from kobald.research.report import render_report
from kobald.research.spec import OptionValue, ResourceBudget, ToleranceSpec
from kobald.runtime.cli import build_runner, main
from kobald.runtime.sandbox import (
    SandboxOutcome,
    SandboxStatus,
    SubprocessSandbox,
)
from kobald.runtime.science import ExperimentRunner, OutputIntegrityError, load_table
from kobald.runtime.science_worker import JOB_FILE, execute_job
from kobald.supervisor.oscillator import DampedOscillatorVerifier
from kobald.supervisor.verification import CheckResult, RunArrays, VerificationReport
from tests.conftest import SpecFactory, oscillator_spec_dict

HUMAN = Principal(PrincipalKind.HUMAN, "researcher")
MODEL = Principal(PrincipalKind.MODEL, "model")
EXAMPLE = Path(__file__).parents[1] / "examples" / "damped_oscillator" / "spec.json"


def _gate() -> ScientificExecutionGate:
    return ScientificExecutionGate(
        ScientificExecutionPolicy(
            allowed_tasks=frozenset({("scipy", "damped_harmonic_oscillator")})
        )
    )


class InProcessBackend:
    """Runs the real worker in-process (fast); optionally sabotages chosen roles."""

    def __init__(self, fail_roles: Sequence[str] = (), corrupt: bool = False) -> None:
        self.fail_roles = set(fail_roles)
        self.corrupt = corrupt

    def execute(
        self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
    ) -> SandboxOutcome:
        workdir.mkdir(parents=True)
        (workdir / JOB_FILE).write_text(json.dumps(job), encoding="utf-8")
        limits = SubprocessSandbox(posix=False).limits(budget)
        role = workdir.name.removeprefix("exec-")
        if role in self.fail_roles:
            return SandboxOutcome(SandboxStatus.CRASHED, -1, 0.0, workdir, None, "boom", limits)
        execute_job(workdir)
        result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
        if self.corrupt:
            table = workdir / result["table"]
            table.write_text(table.read_text(encoding="utf-8").replace("0.0,", "0.5,", 1))
        status = SandboxStatus.OK if result["status"] == "ok" else SandboxStatus.ENGINE_ERROR
        return SandboxOutcome(status, 0, 0.01, workdir, result, "", limits)


def _runner(tmp_path: Path, backend: Any = None, verifiers: Any = None) -> ExperimentRunner:
    return ExperimentRunner(
        registry=default_registry(),
        gate=_gate(),
        backend=backend or InProcessBackend(),
        runs_root=tmp_path / "runs",
        verifiers=[DampedOscillatorVerifier()] if verifiers is None else verifiers,
        clock=lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )


def _saved_record(result_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((result_dir / "record.json").read_text(encoding="utf-8"))
    return record


def test_full_pipeline_with_real_subprocess_sandbox(tmp_path: Path, make_spec: SpecFactory) -> None:
    runner = _runner(tmp_path, backend=SubprocessSandbox())
    result = runner.run(make_spec(), HUMAN)
    assert result.status == "completed", result.record["errors"]
    record = _saved_record(result.run_dir)
    assert record["verification"]["status"] == "passed"
    assert [e["role"] for e in record["executions"]] == ["primary", "replicate", "refined"]
    assert record["executions"][2]["options"]["rtol"] < record["executions"][0]["options"]["rtol"]
    assert record["engine"]["version"] == package_versions(["scipy"])["scipy"]
    assert record["parameters"]["mass"]["si_value"] == pytest.approx(0.25)
    assert record["parameters"]["mass"]["original"] == {"value": 250.0, "unit": "g"}
    assert record["environment"]["packages"]["numpy"] is not None
    # Record integrity: record.sha256 matches the file; artifacts match their hashes.
    text = (result.run_dir / "record.json").read_bytes()
    assert hashlib.sha256(text).hexdigest() == result.record_digest
    for name, digest in record["artifacts"].items():
        assert hashlib.sha256((result.run_dir / name).read_bytes()).hexdigest() == digest
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert "**Verdict: PASSED" in report and "figure.png" in report
    assert "network isolated: False" in report
    # No absolute paths (which would leak the user's home directory) in the record.
    assert str(tmp_path) not in json.dumps(record)


def test_model_request_without_approval_is_not_executed(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    result = _runner(tmp_path).run(make_spec(), MODEL)
    assert result.status == "awaiting_approval"
    assert result.record["executions"] == []
    assert "verification" not in result.record


def test_model_request_with_human_approval_executes(tmp_path: Path, make_spec: SpecFactory) -> None:
    runner = _runner(tmp_path)
    spec = make_spec()
    approval = runner._gate.grant(spec, HUMAN, now=datetime(2026, 11, 23, 11, 59, tzinfo=UTC))
    result = runner.run(spec, MODEL, approval)
    assert result.status == "completed"
    assert result.record["approval"]["approver"]["identifier"] == "researcher"


def test_policy_denial_is_recorded(tmp_path: Path, make_spec: SpecFactory) -> None:
    result = _runner(tmp_path).run(make_spec(budget={"wall_time_s": 10_000}), HUMAN)
    assert result.status == "denied"
    assert (result.run_dir / "report.md").exists()
    assert "Engine `scipy`" in (result.run_dir / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "overrides",
    [
        {"engine": "rdkit"},
        {"parameters": {**oscillator_spec_dict()["parameters"], "mass": {"value": 1, "unit": "m"}}},
        {"options": {"method": "Euler"}},
    ],
    ids=["no-adapter", "wrong-dimension", "bad-option"],
)
def test_invalid_requests_are_recorded_without_execution(
    tmp_path: Path, make_spec: SpecFactory, overrides: dict[str, Any]
) -> None:
    result = _runner(tmp_path).run(make_spec(**overrides), HUMAN)
    assert result.status == "invalid"
    assert result.record["errors"][0]["stage"] == "validation"
    assert result.record["executions"] == []
    assert "Error (validation)" in (result.run_dir / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("role", ["primary", "replicate", "refined"])
def test_execution_failures_are_recorded(tmp_path: Path, make_spec: SpecFactory, role: str) -> None:
    result = _runner(tmp_path, backend=InProcessBackend(fail_roles=[role])).run(make_spec(), HUMAN)
    assert result.status == "failed"
    assert result.record["errors"][-1]["stage"] == f"execution:{role}"
    assert result.record["errors"][-1]["stderr_tail"] == "boom"


def test_engine_error_message_is_recorded(tmp_path: Path, make_spec: SpecFactory) -> None:
    class BrokenBackend(InProcessBackend):
        def execute(
            self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
        ) -> SandboxOutcome:
            return super().execute({**job, "task": "missing"}, workdir, budget)

    result = _runner(tmp_path, backend=BrokenBackend()).run(make_spec(), HUMAN)
    assert result.status == "failed"
    assert "engine_error" in result.record["errors"][0]["message"]
    assert "no task" in result.record["errors"][0]["message"]


def test_tampered_output_fails_integrity_check(tmp_path: Path, make_spec: SpecFactory) -> None:
    result = _runner(tmp_path, backend=InProcessBackend(corrupt=True)).run(make_spec(), HUMAN)
    assert result.status == "failed"
    assert result.record["errors"][0]["stage"] == "output:primary"
    assert "does not match its hash" in result.record["errors"][0]["message"]


def test_tasks_without_reference_are_not_marked_verified(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    result = _runner(tmp_path, verifiers=[]).run(make_spec(), HUMAN)
    assert result.status == "completed"
    assert result.record["verification"]["status"] == "not_verifiable"
    assert len(result.record["executions"]) == 1
    assert not (result.run_dir / "figure.png").exists()
    assert "NOT VERIFIED" in (result.run_dir / "report.md").read_text(encoding="utf-8")


class FailingVerifier(DampedOscillatorVerifier):
    def verify(
        self,
        parameters: Mapping[str, float],
        tolerance: ToleranceSpec,
        primary: RunArrays,
        primary_units: Mapping[str, str],
        replicate: RunArrays,
        refined: RunArrays,
    ) -> VerificationReport:
        return VerificationReport("test", "test", (CheckResult("x", False, 2.0, 1.0, "a|b"),))

    def refinement_options(self, options: Mapping[str, OptionValue]) -> dict[str, OptionValue]:
        return dict(options)


def test_failed_verification_is_reported_honestly(tmp_path: Path, make_spec: SpecFactory) -> None:
    result = _runner(tmp_path, verifiers=[FailingVerifier()]).run(make_spec(), HUMAN)
    assert result.status == "completed_verification_failed"
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert "**FAIL**" in report and "a\\|b" in report


def _table_dir(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    job = {
        "engine": "scipy",
        "task": "damped_harmonic_oscillator",
        "parameters": {
            "mass": 1.0,
            "stiffness": 1.0,
            "damping": 0.0,
            "initial_displacement": 1.0,
            "initial_velocity": 0.0,
            "duration": 1.0,
        },
        "options": {"method": "RK45", "rtol": 1e-6, "atol": 1e-9, "n_samples": 3},
        "seed": None,
    }
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / JOB_FILE).write_text(json.dumps(job), encoding="utf-8")
    execute_job(tmp_path)
    return tmp_path, json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))


def test_load_table_round_trips_exactly(tmp_path: Path) -> None:
    workdir, result = _table_dir(tmp_path)
    arrays, units = load_table(workdir, result)
    assert arrays["time"] == (0.0, 0.5, 1.0)
    assert units == {"time": "s", "displacement": "m", "velocity": "m/s"}


def test_load_table_rejects_path_escape_and_bad_headers(tmp_path: Path) -> None:
    workdir, result = _table_dir(tmp_path)
    with pytest.raises(OutputIntegrityError, match="escapes"):
        load_table(workdir, {**result, "table": "../outside.csv"})
    renamed = [{**c, "name": "t"} if c["name"] == "time" else c for c in result["columns"]]
    with pytest.raises(OutputIntegrityError, match="header"):
        load_table(workdir, {**result, "columns": renamed})


def test_load_table_handles_header_only_tables(tmp_path: Path) -> None:
    workdir, result = _table_dir(tmp_path)
    table = workdir / result["table"]
    table.write_text(table.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(OutputIntegrityError, match="does not match its hash"):
        load_table(workdir, result)


def test_report_for_minimal_record() -> None:
    record = {
        "spec": {"experiment_id": "x", "question": "q?", "engine": "e", "task": "t", "seed": None},
        "record_id": "x-1",
        "record_schema_version": 1,
        "status": "invalid",
        "spec_digest": "0" * 64,
        "created_at": "now",
        "policy": {"decision": "deny", "reasons": ["nope"]},
    }
    text = render_report(record, None)
    assert "deny — nope" in text
    assert "Independent verification" not in text and "## Method" not in text


def test_cli_engines_lists_catalogue() -> None:
    out = io.StringIO()
    assert main(["engines"], out) == 0
    assert "scipy" in out.getvalue() and "adapter_ready" in out.getvalue()
    out = io.StringIO()
    assert main(["engines", "--json"], out) == 0
    assert len(json.loads(out.getvalue())) == 18


def test_cli_runs_the_example_end_to_end(tmp_path: Path) -> None:
    out = io.StringIO()
    code = main(["run", str(EXAMPLE), "--runs-dir", str(tmp_path)], out)
    assert code == 0, out.getvalue()
    assert "verification: passed" in out.getvalue()
    assert "[pass] bitwise_reproducibility" in out.getvalue()


def test_cli_reports_unloadable_and_unsuccessful_specs(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(["run", str(tmp_path / "missing.json")], out) == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(oscillator_spec_dict(engine="rdkit")), encoding="utf-8")
    out = io.StringIO()
    assert main(["run", str(bad), "--runs-dir", str(tmp_path / "runs")], out) == 1
    assert "status: invalid" in out.getvalue()


def test_build_runner_allow_lists_only_registered_tasks(tmp_path: Path) -> None:
    runner = build_runner(tmp_path)
    assert runner._gate.policy.allowed_tasks == frozenset({("scipy", "damped_harmonic_oscillator")})


def test_package_versions_handles_missing_packages() -> None:
    assert package_versions(["kobald-no-such-dist"]) == {"kobald-no-such-dist": None}


class EchoProvider:
    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity("local", "echo", "0")

    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> ModelReply:
        return ModelReply(messages[-1].content[:max_tokens], self.identity)


def test_any_model_can_implement_the_provider_protocol() -> None:
    provider = EchoProvider()
    assert isinstance(provider, ModelProvider)
    reply = provider.complete([Message("user", "hello")], max_tokens=3)
    assert reply.content == "hel" and reply.identity.model == "echo"


def test_failure_records_redact_local_paths(tmp_path: Path, make_spec: SpecFactory) -> None:
    import sys

    leaky = f"Traceback: File {Path.home() / 'x.py'} in {Path(sys.prefix) / 'lib'} at {tmp_path}"

    class LeakyBackend(InProcessBackend):
        def execute(
            self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
        ) -> SandboxOutcome:
            workdir.mkdir(parents=True)
            limits = SubprocessSandbox(posix=False).limits(budget)
            result = {"status": "error", "message": leaky, "traceback": [leaky, 3]}
            return SandboxOutcome(
                SandboxStatus.ENGINE_ERROR, 2, 0.0, workdir, result, leaky, limits
            )

    result = _runner(tmp_path, backend=LeakyBackend()).run(make_spec(), HUMAN)
    assert result.status == "failed"
    saved = (result.run_dir / "record.json").read_text(encoding="utf-8")
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    for text in (saved, report):
        assert str(Path.home()) not in text
        assert json.dumps(str(Path.home()))[1:-1] not in text
    assert "<home>" in saved or "<run_dir>" in saved


def test_redact_paths_handles_nested_values() -> None:
    from kobald.runtime.science import redact_paths

    data = {"a": ["/home/u/x", 1, {"b": "/home/u"}], "c": None}
    assert redact_paths(data, [("/home/u", "<home>")]) == {
        "a": ["<home>/x", 1, {"b": "<home>"}],
        "c": None,
    }
