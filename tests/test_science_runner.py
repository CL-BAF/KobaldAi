"""End-to-end orchestration, budgets, interruption, records, reports and the CLI."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.linalg import expm

from kobald.integrations.science import default_registry
from kobald.policy.science import (
    Principal,
    PrincipalKind,
    ScientificExecutionGate,
    ScientificExecutionPolicy,
)
from kobald.providers.base import Message, ModelIdentity, ModelProvider, ModelReply
from kobald.research.records import package_versions, verify_record
from kobald.research.report import render_report
from kobald.research.spec import OptionValue, ResourceBudget, ToleranceSpec
from kobald.runtime.cli import build_runner, main
from kobald.runtime.sandbox import (
    SandboxLimits,
    SandboxOutcome,
    SandboxStatus,
    SubprocessSandbox,
)
from kobald.runtime.science import (
    ExperimentRunner,
    OutputIntegrityError,
    load_table,
    redact_paths,
)
from kobald.runtime.science_worker import JOB_FILE, execute_job
from kobald.supervisor.oscillator import DampedOscillatorVerifier
from kobald.supervisor.verification import CheckResult, RunArrays, VerificationReport
from tests.conftest import SpecFactory, oscillator_spec_dict

HUMAN = Principal(PrincipalKind.HUMAN, "researcher")
MODEL = Principal(PrincipalKind.MODEL, "model")
EXAMPLE = Path(__file__).parents[1] / "examples" / "damped_oscillator" / "spec.json"
TASKS = frozenset({("scipy", "damped_harmonic_oscillator")})


def _limits(budget: ResourceBudget) -> SandboxLimits:
    return SandboxLimits(
        backend="in-process-test",
        controller="none",
        wall_time_s=budget.wall_time_s,
        max_output_bytes=budget.max_output_bytes,
        memory_mb=budget.memory_mb,
        memory_limit_kind=None,
        process_tree_controlled=False,
        network_isolated=False,
        filesystem_confined=False,
        privileges_reduced=False,
        environment_scrubbed=False,
    )


class InProcessBackend:
    """Runs the real worker in-process (fast); optionally sabotages chosen roles."""

    def __init__(
        self,
        fail_roles: Sequence[str] = (),
        corrupt: bool = False,
        interrupt_role: str | None = None,
    ) -> None:
        self.fail_roles = set(fail_roles)
        self.corrupt = corrupt
        self.interrupt_role = interrupt_role
        self.allowances: list[ResourceBudget] = []
        self.statuses_seen: list[str] = []

    def execute(
        self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
    ) -> SandboxOutcome:
        self.allowances.append(budget)
        record = json.loads((workdir.parent / "record.json").read_text(encoding="utf-8"))
        self.statuses_seen.append(record["status"])
        role = workdir.name.removeprefix("exec-")
        if role == self.interrupt_role:
            raise KeyboardInterrupt
        workdir.mkdir(parents=True)
        (workdir / JOB_FILE).write_text(json.dumps(job), encoding="utf-8")
        if role in self.fail_roles:
            return SandboxOutcome(
                SandboxStatus.CRASHED, -1, 0.0, workdir, None, "boom", _limits(budget)
            )
        execute_job(workdir)
        result = json.loads((workdir / "result.json").read_text(encoding="utf-8"))
        if self.corrupt:
            table = workdir / result["table"]
            table.write_text(table.read_text(encoding="utf-8").replace("0.0,", "0.5,", 1))
        status = SandboxStatus.OK if result["status"] == "ok" else SandboxStatus.ENGINE_ERROR
        return SandboxOutcome(status, 0, 0.01, workdir, result, "", _limits(budget))


class FakeClock:
    """Monotonic clock advancing a fixed step per call."""

    def __init__(self, step: float) -> None:
        self.now = 1000.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def _runner(
    tmp_path: Path,
    backend: Any = None,
    verifiers: Any = None,
    allow_model_requests: bool = False,
    monotonic: Any = None,
) -> ExperimentRunner:
    gate = ScientificExecutionGate(
        ScientificExecutionPolicy(allowed_tasks=TASKS, allow_model_requests=allow_model_requests)
    )
    extra = {} if monotonic is None else {"monotonic": monotonic}
    return ExperimentRunner(
        registry=default_registry(),
        gate=gate,
        backend=backend or InProcessBackend(),
        runs_root=tmp_path / "runs",
        verifiers=[DampedOscillatorVerifier()] if verifiers is None else verifiers,
        clock=lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
        **extra,
    )


def _saved(run_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
    return record


def _result_json(run_dir: Path, role: str = "primary") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (run_dir / f"exec-{role}" / "result.json").read_text(encoding="utf-8")
    )
    return data


def _expm_reference(record: dict[str, Any], t: np.ndarray) -> np.ndarray:
    """Exact propagation x(t) = expm(A t) x0 — independent of solver and verifier."""
    p = {k: v["si_value"] for k, v in record["parameters"].items()}
    a = np.array([[0.0, 1.0], [-p["stiffness"] / p["mass"], -p["damping"] / p["mass"]]])
    y0 = np.array([p["initial_displacement"], p["initial_velocity"]])
    return np.array([expm(a * ti) @ y0 for ti in t])


# --- full pipeline ------------------------------------------------------------------


def test_full_pipeline_is_numerically_correct_with_real_sandbox(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    result = _runner(tmp_path, backend=SubprocessSandbox()).run(make_spec(), HUMAN)
    assert result.status == "completed", result.record["errors"]
    record = _saved(result.run_dir)
    assert record["verification"]["status"] == "passed"
    assert [e["role"] for e in record["executions"]] == ["primary", "replicate", "refined"]

    # Numerical correctness, checked here independently of the supervisor verifier.
    arrays, units = load_table(result.run_dir / "exec-primary", _result_json(result.run_dir))
    t = np.asarray(arrays["time"])
    reference = _expm_reference(record, t)
    tolerance = 1e-10 + 1e-7 * float(np.max(np.abs(reference[:, 0])))
    err_primary = float(np.max(np.abs(np.asarray(arrays["displacement"]) - reference[:, 0])))
    assert err_primary < tolerance
    assert units["displacement"] == "m"
    refined, _ = load_table(
        result.run_dir / "exec-refined", _result_json(result.run_dir, "refined")
    )
    err_refined = float(np.max(np.abs(np.asarray(refined["displacement"]) - reference[:, 0])))
    assert err_refined <= err_primary

    # Provenance and integrity.
    assert record["engine"]["version"] == package_versions(["scipy"])["scipy"]
    assert record["parameters"]["mass"]["original"] == {"value": 250.0, "unit": "g"}
    assert record["parameters"]["mass"]["si_value"] == pytest.approx(0.25)
    assert record["budget"]["scope"] == "experiment_total"
    assert 0 < record["budget"]["wall_time_used_s"] <= record["budget"]["wall_time_s"]
    assert record["record_schema_version"] == 2
    assert verify_record(result.run_dir) == []
    text = (result.run_dir / "record.json").read_bytes()
    assert hashlib.sha256(text).hexdigest() == result.record_digest
    report = (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert "**Verdict: PASSED" in report and "figure.png" in report
    assert "network isolated: False" in report and "experiment_total" in report
    assert str(tmp_path) not in json.dumps(record)


# --- total experiment budget --------------------------------------------------------


def test_budget_is_shared_across_executions(tmp_path: Path, make_spec: SpecFactory) -> None:
    backend = InProcessBackend()
    result = _runner(tmp_path, backend=backend, monotonic=FakeClock(1.0)).run(
        make_spec(budget={"wall_time_s": 60}), HUMAN
    )
    assert result.status == "completed"
    walls = [a.wall_time_s for a in backend.allowances]
    assert walls[0] < 60 and walls[1] < walls[0] and walls[2] < walls[1]
    outputs = [a.max_output_bytes for a in backend.allowances]
    assert outputs[1] < outputs[0] and outputs[2] < outputs[1]
    assert result.record["budget"]["output_bytes_used"] > 0


@pytest.mark.parametrize(
    ("budget", "stage"),
    [
        ({"wall_time_s": 2.5}, "budget:replicate"),
        ({"wall_time_s": 4.5}, "budget:refined"),
        ({"wall_time_s": 60, "max_output_bytes": 1}, "budget:replicate"),
    ],
    ids=["time-before-replicate", "time-before-refined", "output-bytes"],
)
def test_budget_exhaustion_fails_instead_of_skipping_verification(
    tmp_path: Path, make_spec: SpecFactory, budget: dict[str, Any], stage: str
) -> None:
    result = _runner(tmp_path, monotonic=FakeClock(1.0)).run(make_spec(budget=budget), HUMAN)
    assert result.status == "failed"
    assert result.record["errors"][-1]["stage"] == stage
    assert "verification" not in result.record


# --- policy outcomes ----------------------------------------------------------------


def test_model_requests_are_denied_by_default(tmp_path: Path, make_spec: SpecFactory) -> None:
    result = _runner(tmp_path).run(make_spec(), MODEL)
    assert result.status == "denied"
    assert result.record["executions"] == []


def test_model_request_without_approval_awaits_approval(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    result = _runner(tmp_path, allow_model_requests=True).run(make_spec(), MODEL)
    assert result.status == "awaiting_approval"
    assert result.record["executions"] == []
    assert "verification" not in result.record


def test_model_request_with_human_approval_executes_once(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    runner = _runner(tmp_path, allow_model_requests=True)
    spec = make_spec()
    approval = runner._gate.grant(spec, HUMAN, now=datetime(2026, 11, 23, 11, 59, tzinfo=UTC))
    assert runner.run(spec, MODEL, approval).status == "completed"
    replay = runner.run(spec, MODEL, approval)
    assert replay.status == "denied"
    assert replay.record["policy"]["reasons"] == ["approval has already been used"]


def test_policy_denial_is_recorded(tmp_path: Path, make_spec: SpecFactory) -> None:
    result = _runner(tmp_path).run(make_spec(budget={"wall_time_s": 10_000}), HUMAN)
    assert result.status == "denied"
    assert "Engine `scipy`" in (result.run_dir / "report.md").read_text(encoding="utf-8")
    assert verify_record(result.run_dir) == []


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


# --- failures and interruption ------------------------------------------------------


@pytest.mark.parametrize("role", ["primary", "replicate", "refined"])
def test_execution_failures_are_recorded_and_stop_the_run(
    tmp_path: Path, make_spec: SpecFactory, role: str
) -> None:
    backend = InProcessBackend(fail_roles=[role])
    result = _runner(tmp_path, backend=backend).run(make_spec(), HUMAN)
    assert result.status == "failed"
    assert result.record["errors"][-1]["stage"] == f"execution:{role}"
    assert result.record["errors"][-1]["stderr_tail"] == "boom"
    assert result.record["executions"][-1]["role"] == role  # nothing ran after the failure
    assert verify_record(result.run_dir) == []


def test_record_is_running_while_executions_are_in_progress(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    backend = InProcessBackend()
    _runner(tmp_path, backend=backend).run(make_spec(), HUMAN)
    assert backend.statuses_seen == ["running", "running", "running"]


def test_interrupted_run_leaves_a_consistent_record(tmp_path: Path, make_spec: SpecFactory) -> None:
    runner = _runner(tmp_path, backend=InProcessBackend(interrupt_role="replicate"))
    with pytest.raises(KeyboardInterrupt):
        runner.run(make_spec(), HUMAN)
    (run_dir,) = (tmp_path / "runs").iterdir()
    record = _saved(run_dir)
    assert record["status"] == "interrupted"
    assert record["errors"][-1] == {"stage": "interrupted", "message": "KeyboardInterrupt: "}
    assert [e["role"] for e in record["executions"]] == ["primary"]
    assert verify_record(run_dir) == ["record is incomplete (status 'interrupted')"]
    assert "Status:** interrupted" in (run_dir / "report.md").read_text(encoding="utf-8")


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


def test_failure_records_redact_local_paths(tmp_path: Path, make_spec: SpecFactory) -> None:
    leaky = f"Traceback: File {Path.home() / 'x.py'} in {Path(sys.prefix) / 'lib'} at {tmp_path}"

    class LeakyBackend(InProcessBackend):
        def execute(
            self, job: Mapping[str, Any], workdir: Path, budget: ResourceBudget
        ) -> SandboxOutcome:
            workdir.mkdir(parents=True)
            result = {"status": "error", "message": leaky, "traceback": [leaky, 3]}
            return SandboxOutcome(
                SandboxStatus.ENGINE_ERROR, 2, 0.0, workdir, result, leaky, _limits(budget)
            )

    result = _runner(tmp_path, backend=LeakyBackend()).run(make_spec(), HUMAN)
    assert result.status == "failed"
    for name in ("record.json", "report.md"):
        text = (result.run_dir / name).read_text(encoding="utf-8")
        assert str(Path.home()) not in text
        assert json.dumps(str(Path.home()))[1:-1] not in text


def test_redact_paths_handles_nested_values() -> None:
    data = {"a": ["/home/u/x", 1, {"b": "/home/u"}], "c": None}
    assert redact_paths(data, [("/home/u", "<home>")]) == {
        "a": ["<home>/x", 1, {"b": "<home>"}],
        "c": None,
    }


# --- record verification ------------------------------------------------------------


def test_verify_record_detects_tampering_and_missing_files(
    tmp_path: Path, make_spec: SpecFactory
) -> None:
    result = _runner(tmp_path).run(make_spec(), HUMAN)
    run_dir = result.run_dir
    assert verify_record(run_dir) == []
    (run_dir / "exec-primary" / "outputs" / "table.csv").write_text("tampered")
    (run_dir / "figure.png").unlink()
    problems = verify_record(run_dir)
    assert "artifact exec-primary/outputs/table.csv does not match its recorded hash" in problems
    assert "artifact figure.png is missing" in problems
    record_path = run_dir / "record.json"
    record_path.write_text(record_path.read_text(encoding="utf-8").replace("completed", "x"))
    assert "record.json does not match record.sha256" in verify_record(run_dir)
    (run_dir / "record.sha256").unlink()
    assert "record.sha256 is missing" in verify_record(run_dir)
    record_path.write_text("{broken")
    assert verify_record(run_dir)[-1] == "record.json is not valid JSON"
    record_path.unlink()
    assert verify_record(run_dir) == ["record.json is missing"]


# --- table loading ------------------------------------------------------------------


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
    record: dict[str, Any] = {
        "spec": {"experiment_id": "x", "question": "q?", "engine": "e", "task": "t", "seed": None},
        "record_id": "x-1",
        "record_schema_version": 2,
        "status": "interrupted",
        "spec_digest": "0" * 64,
        "created_at": "now",
    }
    text = render_report(record, None)
    assert "Policy decision" not in text and "Status:** interrupted" in text
    record["policy"] = {"decision": "deny", "reasons": ["nope"]}
    assert "deny — nope" in render_report(record, None)


# --- CLI ----------------------------------------------------------------------------


def test_cli_engines_lists_catalogue() -> None:
    out = io.StringIO()
    assert main(["engines"], out) == 0
    assert "scipy" in out.getvalue() and "adapter_ready" in out.getvalue()
    out = io.StringIO()
    assert main(["engines", "--json"], out) == 0
    assert len(json.loads(out.getvalue())) == 18


def test_cli_runs_the_example_end_to_end_and_verifies_it(tmp_path: Path) -> None:
    out = io.StringIO()
    code = main(["run", str(EXAMPLE), "--runs-dir", str(tmp_path)], out)
    assert code == 0, out.getvalue()
    assert "verification: passed" in out.getvalue()
    (run_dir,) = tmp_path.iterdir()
    out = io.StringIO()
    assert main(["verify-record", str(run_dir)], out) == 0
    assert out.getvalue() == "record verified\n"
    (run_dir / "report.md").write_text("edited")
    out = io.StringIO()
    assert main(["verify-record", str(run_dir)], out) == 1
    assert "problem: artifact report.md does not match its recorded hash" in out.getvalue()


def test_cli_reports_unloadable_and_unsuccessful_specs(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(["run", str(tmp_path / "missing.json")], out) == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(oscillator_spec_dict(engine="rdkit")), encoding="utf-8")
    out = io.StringIO()
    assert main(["run", str(bad), "--runs-dir", str(tmp_path / "runs")], out) == 1
    assert "status: invalid" in out.getvalue()


def test_build_runner_keeps_model_requests_disabled(tmp_path: Path) -> None:
    runner = build_runner(tmp_path)
    assert runner._gate.policy.allowed_tasks == TASKS | {("qutip", "rabi_two_level")}
    assert runner._gate.policy.allow_model_requests is False


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
