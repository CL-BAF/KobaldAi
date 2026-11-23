"""Independent verification: the closed-form reference and the oscillator verifier."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
import sympy as sp

from kobald.research.spec import ToleranceSpec
from kobald.supervisor.oscillator import DampedOscillatorVerifier, analytic_oscillator
from kobald.supervisor.verification import (
    CheckResult,
    VerificationReport,
    VerificationStatus,
    not_verifiable,
)

SRC = Path(__file__).parents[1] / "src" / "kobald"


@pytest.mark.parametrize(
    ("m", "k", "c"),
    [(2.0, 8.0, 0.8), (2.0, 8.0, 8.0), (2.0, 8.0, 20.0), (1.0, 1.0, 0.0)],
    ids=["underdamped", "critical", "overdamped", "undamped"],
)
def test_closed_form_matches_sympy_dsolve(m: float, k: float, c: float) -> None:
    """Cross-check the hand-derived reference against a symbolic ODE solution."""
    t = sp.symbols("t", real=True)
    x = sp.Function("x")
    x0, v0 = 0.3, -1.2
    # Decimal-exact rationals (Rational("0.8") == 4/5) keep dsolve fast and exact.
    m_r, c_r, k_r = (sp.Rational(str(value)) for value in (m, c, k))
    ode = sp.Eq(m_r * x(t).diff(t, 2) + c_r * x(t).diff(t) + k_r * x(t), 0)
    ics = {x(0): sp.Rational(3, 10), x(t).diff(t).subs(t, 0): sp.Rational(-6, 5)}
    solution = sp.dsolve(ode, ics=ics).rhs
    x_fn = sp.lambdify(t, solution, "numpy")
    v_fn = sp.lambdify(t, solution.diff(t), "numpy")
    times = np.linspace(0.0, 5.0, 101)
    x_ref, v_ref = analytic_oscillator(times, m, k, c, x0, v0)
    np.testing.assert_allclose(x_ref, np.real(x_fn(times)), rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(v_ref, np.real(v_fn(times)), rtol=1e-12, atol=1e-14)


def _arrays(t: np.ndarray, x: np.ndarray, v: np.ndarray) -> dict[str, tuple[float, ...]]:
    return {
        "time": tuple(map(float, t)),
        "displacement": tuple(map(float, x)),
        "velocity": tuple(map(float, v)),
    }


PARAMS = {
    "mass": 1.0,
    "stiffness": 4.0,
    "damping": 0.4,
    "initial_displacement": 1.0,
    "initial_velocity": 0.0,
    "duration": 3.0,
}
UNITS = {"time": "s", "displacement": "m", "velocity": "m/s"}
TOL = ToleranceSpec(rtol=1e-6, atol=1e-9)


def _exact() -> dict[str, tuple[float, ...]]:
    t = np.linspace(0.0, PARAMS["duration"], 301)
    return _arrays(t, *analytic_oscillator(t, 1.0, 4.0, 0.4, 1.0, 0.0))


def _perturbed(eps: float) -> dict[str, tuple[float, ...]]:
    exact = _exact()
    t = np.asarray(exact["time"])
    return _arrays(t, np.asarray(exact["displacement"]) + eps, np.asarray(exact["velocity"]) + eps)


def _checks(report: VerificationReport) -> dict[str, bool]:
    return {check.name: check.passed for check in report.checks}


def test_verifier_passes_exact_data() -> None:
    verifier = DampedOscillatorVerifier()
    report = verifier.verify(PARAMS, TOL, _exact(), UNITS, _exact(), _exact())
    assert report.status is VerificationStatus.PASSED, report.to_dict()
    assert set(report.reference_series) == {"time", "displacement", "velocity"}
    assert report.to_dict()["verifier"].endswith("DampedOscillatorVerifier")
    assert verifier.key == ("scipy", "damped_harmonic_oscillator")


def test_verifier_detects_inaccurate_output() -> None:
    report = DampedOscillatorVerifier().verify(
        PARAMS, TOL, _perturbed(1e-3), UNITS, _perturbed(1e-3), _perturbed(1e-3)
    )
    checks = _checks(report)
    assert report.status is VerificationStatus.FAILED
    assert not checks["displacement_vs_closed_form"]
    assert not checks["velocity_vs_closed_form"]


def test_verifier_detects_wrong_units() -> None:
    units = {**UNITS, "displacement": "mm"}
    report = DampedOscillatorVerifier().verify(PARAMS, TOL, _exact(), units, _exact(), _exact())
    assert _checks(report)["units"] is False


def test_verifier_detects_bad_time_grid() -> None:
    bad = dict(_exact())
    bad["time"] = tuple(v * 0.5 for v in bad["time"])
    report = DampedOscillatorVerifier().verify(PARAMS, TOL, bad, UNITS, bad, bad)
    assert _checks(report)["time_grid"] is False


def test_verifier_detects_energy_gain() -> None:
    exact = _exact()
    t = np.asarray(exact["time"])
    grown = _arrays(
        t, np.asarray(exact["displacement"]) * np.exp(0.5 * t), np.asarray(exact["velocity"])
    )
    report = DampedOscillatorVerifier().verify(PARAMS, TOL, grown, UNITS, grown, grown)
    assert _checks(report)["energy_non_increasing"] is False


def test_verifier_detects_non_convergence_and_non_reproducibility() -> None:
    report = DampedOscillatorVerifier().verify(
        PARAMS, TOL, _perturbed(1e-10), UNITS, _perturbed(2e-10), _perturbed(1e-8)
    )
    checks = _checks(report)
    assert checks["convergence_under_refinement"] is False
    assert checks["bitwise_reproducibility"] is False


def test_refinement_tightens_and_clamps_tolerances() -> None:
    verifier = DampedOscillatorVerifier()
    assert verifier.refinement_options({"rtol": 1e-8, "atol": 1e-10, "method": "RK45"}) == {
        "rtol": 1e-10,
        "atol": 1e-12,
        "method": "RK45",
    }
    clamped = verifier.refinement_options({"rtol": 1e-14, "atol": 1e-16})
    assert clamped == {"rtol": 1e-14, "atol": 1e-16}


def test_report_status_vocabulary() -> None:
    passing = CheckResult("a", True, 1.0, 2.0, "")
    failing = CheckResult("b", False, 3.0, 2.0, "")
    assert VerificationReport("v", "r", (passing,)).status is VerificationStatus.PASSED
    assert VerificationReport("v", "r", (passing, failing)).status is VerificationStatus.FAILED
    empty = not_verifiable("no reference")
    assert empty.status is VerificationStatus.NOT_VERIFIABLE
    assert empty.to_dict() == {
        "status": "not_verifiable",
        "verifier": "none",
        "reference": "no reference",
        "checks": [],
    }


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("supervisor", ("kobald.integrations", "kobald.runtime", "kobald.providers", "qutip")),
        ("integrations", ("kobald.supervisor", "kobald.policy", "kobald.providers")),
        ("providers", ("kobald.policy", "kobald.runtime", "kobald.supervisor")),
        ("policy", ("kobald.integrations", "kobald.runtime", "kobald.supervisor")),
        ("research", ("kobald.integrations", "kobald.runtime", "kobald.supervisor")),
    ],
)
def test_domain_boundaries(package: str, forbidden: tuple[str, ...]) -> None:
    """Verifiers stay independent of engines; models and engines cannot reach authority."""
    for path in (SRC / package).rglob("*.py"):
        for module in _imported_modules(path):
            assert not module.startswith(forbidden), f"{path} imports {module}"
