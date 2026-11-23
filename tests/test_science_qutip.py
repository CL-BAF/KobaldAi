"""QuTiP two-level Rabi adapter, its independent verifier and end-to-end runs.

Numerical correctness is checked against an exact matrix exponential of the
2x2 Hamiltonian, which is independent of both QuTiP and the supervisor's
closed-form reference.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.linalg import expm

from kobald.integrations.science import AdapterError, default_registry
from kobald.integrations.science.adapters.qutip_rabi import RABI_TWO_LEVEL, QutipRabiAdapter
from kobald.policy.science import (
    Principal,
    PrincipalKind,
    ScientificExecutionGate,
    ScientificExecutionPolicy,
)
from kobald.research.records import package_versions, verify_record
from kobald.research.spec import ExperimentSpec, OptionValue, ToleranceSpec
from kobald.runtime.cli import main
from kobald.runtime.sandbox import SubprocessSandbox
from kobald.runtime.science import ExperimentRunner, load_table
from kobald.supervisor.rabi import RabiVerifier, analytic_rabi
from kobald.supervisor.verification import VerificationStatus

HUMAN = Principal(PrincipalKind.HUMAN, "researcher")
EXAMPLE = Path(__file__).parents[1] / "examples" / "rabi_two_level" / "spec.json"
TWO_PI = 2 * np.pi
OPTIONS: dict[str, OptionValue] = {
    "method": "dop853",
    "rtol": 1e-10,
    "atol": 1e-12,
    "nsteps": 100_000,
    "n_samples": 201,
}

_SX = np.array([[0, 1], [1, 0]], dtype=complex)
_SY = np.array([[0, -1j], [1j, 0]], dtype=complex)
_SZ = np.diag([1.0, -1.0]).astype(complex)


def expm_reference(t: np.ndarray, omega: float, delta: float) -> dict[str, np.ndarray]:
    """|psi(t)> = expm(-i H t)|0>, observables computed directly from the state."""
    hamiltonian = 0.5 * delta * _SZ + 0.5 * omega * _SX
    states = [expm(-1j * hamiltonian * ti) @ np.array([1.0, 0.0], dtype=complex) for ti in t]

    def expect(op: np.ndarray) -> np.ndarray:
        return np.array([np.real(np.conj(s) @ op @ s) for s in states])

    return {
        "population_0": np.array([abs(s[0]) ** 2 for s in states]),
        "population_1": np.array([abs(s[1]) ** 2 for s in states]),
        "sigma_x": expect(_SX),
        "sigma_y": expect(_SY),
    }


CASES = [
    (TWO_PI * 1e6, 0.0),
    (TWO_PI * 1e6, TWO_PI * 0.25e6),
    (TWO_PI * 1e6, -TWO_PI * 0.4e6),
    (TWO_PI * 0.3e6, TWO_PI * 2e6),
]
CASE_IDS = ["resonant", "detuned", "negative-detuning", "far-detuned"]


@pytest.mark.parametrize(("omega", "delta"), CASES, ids=CASE_IDS)
def test_closed_form_reference_matches_matrix_exponential(omega: float, delta: float) -> None:
    t = np.linspace(0.0, 3e-6, 151)
    closed = analytic_rabi(t, omega, delta)
    exact = expm_reference(t, omega, delta)
    for name in exact:
        np.testing.assert_allclose(closed[name], exact[name], atol=1e-12)


@pytest.mark.parametrize(("omega", "delta"), CASES, ids=CASE_IDS)
def test_qutip_adapter_matches_matrix_exponential(omega: float, delta: float) -> None:
    params = {"rabi_frequency": omega, "detuning": delta, "duration": 3e-6}
    result = QutipRabiAdapter().run("rabi_two_level", params, OPTIONS, seed=None)
    t = np.asarray(result.columns["time"].values)
    exact = expm_reference(t, omega, delta)
    for name, reference in exact.items():
        assert np.max(np.abs(np.asarray(result.columns[name].values) - reference)) < 1e-9, name
    assert result.engine_version == package_versions(["qutip"])["qutip"]
    assert float(result.diagnostics["max_imaginary_expectation"]) < 1e-12


def test_resonant_drive_reaches_full_inversion_at_pi_time() -> None:
    omega = TWO_PI * 1e6
    params = {"rabi_frequency": omega, "detuning": 0.0, "duration": np.pi / omega}
    result = QutipRabiAdapter().run("rabi_two_level", params, {**OPTIONS, "n_samples": 3}, None)
    assert result.columns["population_1"].values[-1] == pytest.approx(1.0, abs=1e-9)
    assert result.columns["population_1"].values[1] == pytest.approx(0.5, abs=1e-9)


def test_adapter_rejects_unknown_task() -> None:
    with pytest.raises(AdapterError, match="unsupported task"):
        QutipRabiAdapter().run("spin_echo", {}, OPTIONS, None)


def test_genuine_solver_failure_is_reported() -> None:
    params = {"rabi_frequency": TWO_PI * 1e6, "detuning": 0.0, "duration": 3e-6}
    options = {**OPTIONS, "method": "adams", "rtol": 1e-12, "atol": 1e-14, "nsteps": 1}
    with pytest.warns(UserWarning), pytest.raises(AdapterError, match="IntegratorException"):
        QutipRabiAdapter().run("rabi_two_level", params, options, None)


def test_task_contract_requires_angular_units() -> None:
    contract = RABI_TWO_LEVEL.to_dict()
    assert contract["parameters"]["rabi_frequency"]["requires_angle_unit"] is True
    assert contract["outputs"]["population_1"] == "1"
    assert set(default_registry().tasks()) == {
        ("scipy", "damped_harmonic_oscillator"),
        ("qutip", "rabi_two_level"),
    }


# --- verifier -----------------------------------------------------------------------

PARAMS = {"rabi_frequency": TWO_PI * 1e6, "detuning": TWO_PI * 0.25e6, "duration": 3e-6}
UNITS = {"time": "s", "population_0": "1", "population_1": "1", "sigma_x": "1", "sigma_y": "1"}
TOL = ToleranceSpec(rtol=1e-9, atol=1e-9)


def _arrays(**perturb: float) -> dict[str, tuple[float, ...]]:
    t = np.linspace(0.0, PARAMS["duration"], 201)
    exact = analytic_rabi(t, PARAMS["rabi_frequency"], PARAMS["detuning"])
    data = {"time": tuple(map(float, t))}
    for name, values in exact.items():
        data[name] = tuple(map(float, values + perturb.get(name, 0.0)))
    return data


def _checks(primary: Any, replicate: Any = None, refined: Any = None, units: Any = None) -> Any:
    report = RabiVerifier().verify(
        PARAMS,
        TOL,
        primary,
        units or UNITS,
        replicate or primary,
        refined or primary,
    )
    return report, {c.name: c.passed for c in report.checks}


def test_verifier_passes_exact_data() -> None:
    report, checks = _checks(_arrays())
    assert report.status is VerificationStatus.PASSED, checks
    assert set(report.reference_series) == {"time", *UNITS} - {"time"} | {"time"}
    assert RabiVerifier().key == ("qutip", "rabi_two_level")


def test_verifier_detects_wrong_dynamics() -> None:
    _report, checks = _checks(_arrays(population_1=1e-6, sigma_y=1e-6))
    assert not checks["population_1_vs_closed_form"]
    assert not checks["sigma_y_vs_closed_form"]
    assert not checks["probability_conservation"]


def test_verifier_detects_non_unit_bloch_vector() -> None:
    _report, checks = _checks(_arrays(sigma_x=1e-3))
    assert not checks["bloch_vector_unit_length"]


def test_verifier_detects_population_outside_bounds() -> None:
    _report, checks = _checks(_arrays(population_1=-1e-3, population_0=1e-3))
    assert checks["probability_conservation"]
    assert not checks["population_bounds"]


def test_verifier_detects_units_grid_convergence_and_reproducibility() -> None:
    bad_grid = dict(_arrays())
    bad_grid["time"] = tuple(v * 0.5 for v in bad_grid["time"])
    _r, checks = _checks(bad_grid, units={**UNITS, "sigma_x": "m"})
    assert not checks["units"] and not checks["time_grid"]
    _r, checks = _checks(
        _arrays(population_1=1e-12),
        replicate=_arrays(population_1=2e-12),
        refined=_arrays(population_1=1e-10),
    )
    assert not checks["convergence_under_refinement"]
    assert not checks["bitwise_reproducibility"]


def test_refinement_tightens_and_clamps() -> None:
    verifier = RabiVerifier()
    assert verifier.refinement_options({"rtol": 1e-8, "atol": 1e-10})["rtol"] == 1e-10
    assert verifier.refinement_options({"rtol": 1e-14, "atol": 1e-16}) == {
        "rtol": 1e-14,
        "atol": 1e-16,
    }


# --- end to end ---------------------------------------------------------------------


def _runner(tmp_path: Path) -> ExperimentRunner:
    tasks = frozenset(default_registry().tasks())
    return ExperimentRunner(
        registry=default_registry(),
        gate=ScientificExecutionGate(ScientificExecutionPolicy(allowed_tasks=tasks)),
        backend=SubprocessSandbox(),
        runs_root=tmp_path / "runs",
        verifiers=[RabiVerifier()],
        clock=lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )


def _spec(**overrides: Any) -> ExperimentSpec:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["options"]["n_samples"] = 201
    data.update(overrides)
    return ExperimentSpec.from_dict(data)


def test_end_to_end_rabi_run_is_correct_and_fully_recorded(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(_spec(), HUMAN)
    assert result.status == "completed", result.record["errors"]
    record = result.record
    assert record["verification"]["status"] == "passed"
    assert record["engine"]["id"] == "qutip"
    assert record["engine"]["version"] == package_versions(["qutip"])["qutip"]
    assert record["environment"]["packages"]["qutip"] == record["engine"]["version"]
    assert record["parameters"]["rabi_frequency"]["original"]["unit"] == "Mrad/s"
    assert record["parameters"]["rabi_frequency"]["si_value"] == pytest.approx(TWO_PI * 1e6)
    assert record["parameters"]["duration"]["si_value"] == pytest.approx(3e-6)
    assert verify_record(result.run_dir) == []

    run_dir = result.run_dir / "exec-primary"
    data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    arrays, _units = load_table(run_dir, data)
    t = np.asarray(arrays["time"])
    exact = expm_reference(t, TWO_PI * 1e6, TWO_PI * 0.25e6)
    for name, reference in exact.items():
        assert np.max(np.abs(np.asarray(arrays[name]) - reference)) < 1e-9, name


def test_hertz_is_rejected_before_execution(tmp_path: Path) -> None:
    params = json.loads(EXAMPLE.read_text(encoding="utf-8"))["parameters"]
    params["rabi_frequency"] = {"value": 1.0, "unit": "MHz"}
    result = _runner(tmp_path).run(_spec(parameters=params), HUMAN)
    assert result.status == "invalid"
    assert "2*pi" in result.record["errors"][0]["message"]
    assert result.record["executions"] == []


def test_solver_failure_inside_sandbox_is_recorded(tmp_path: Path) -> None:
    options = {**json.loads(EXAMPLE.read_text(encoding="utf-8"))["options"]}
    options.update({"method": "adams", "nsteps": 1, "rtol": 1e-12, "atol": 1e-14})
    result = _runner(tmp_path).run(_spec(options=options), HUMAN)
    assert result.status == "failed"
    assert result.record["errors"][0]["stage"] == "execution:primary"
    assert "IntegratorException" in result.record["errors"][0]["message"]
    assert verify_record(result.run_dir) == []


def test_cli_runs_the_rabi_example(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(["run", str(EXAMPLE), "--runs-dir", str(tmp_path)], out) == 0, out.getvalue()
    assert "[pass] bloch_vector_unit_length" in out.getvalue()
