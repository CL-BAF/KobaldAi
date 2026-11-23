"""Independent closed-form reference for the damped harmonic oscillator.

For ``m x'' + c x' + k x = 0`` with ``w0 = sqrt(k/m)`` and
``zeta = c / (2 sqrt(k m))`` the textbook solutions are:

* under-damped (zeta < 1), ``wd = w0 sqrt(1 - zeta^2)``:
  ``x = exp(-zeta w0 t) (x0 cos(wd t) + (v0 + zeta w0 x0)/wd sin(wd t))``
* critically damped (zeta = 1): ``x = exp(-w0 t) (x0 + (v0 + w0 x0) t)``
* over-damped (zeta > 1): ``x = A exp(r1 t) + B exp(r2 t)``,
  ``r1,2 = -w0 (zeta -/+ sqrt(zeta^2 - 1))``

This module must not import any engine adapter (enforced by a test).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pint

from kobald.research.hashing import float_array_sha256
from kobald.research.spec import OptionValue, ToleranceSpec
from kobald.supervisor.verification import CheckResult, RunArrays, VerificationReport

__all__ = ["DampedOscillatorVerifier", "analytic_oscillator"]

_EXPECTED_UNITS = {"time": "s", "displacement": "m", "velocity": "m/s"}
_CRITICAL_BAND = 1e-12
_REFINEMENT_FACTOR = 100.0


def analytic_oscillator(
    t: np.ndarray, m: float, k: float, c: float, x0: float, v0: float
) -> tuple[np.ndarray, np.ndarray]:
    """Closed-form displacement and velocity of a free damped oscillator."""
    w0 = np.sqrt(k / m)
    zeta = c / (2.0 * np.sqrt(k * m))
    if abs(zeta - 1.0) <= _CRITICAL_BAND:
        b = v0 + w0 * x0
        decay = np.exp(-w0 * t)
        return decay * (x0 + b * t), decay * (b - w0 * (x0 + b * t))
    if zeta < 1.0:
        a = zeta * w0
        wd = w0 * np.sqrt(1.0 - zeta**2)
        b = (v0 + a * x0) / wd
        decay = np.exp(-a * t)
        cos, sin = np.cos(wd * t), np.sin(wd * t)
        x = decay * (x0 * cos + b * sin)
        v = decay * ((b * wd - a * x0) * cos - (a * b + x0 * wd) * sin)
        return x, v
    s = w0 * np.sqrt(zeta**2 - 1.0)
    r1, r2 = -zeta * w0 + s, -zeta * w0 - s
    a_coef = (v0 - r2 * x0) / (r1 - r2)
    b_coef = x0 - a_coef
    e1, e2 = np.exp(r1 * t), np.exp(r2 * t)
    return a_coef * e1 + b_coef * e2, a_coef * r1 * e1 + b_coef * r2 * e2


def _max_error(values: tuple[float, ...], reference: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(values) - reference)))


class DampedOscillatorVerifier:
    """Verifies ``scipy/damped_harmonic_oscillator`` against the closed form."""

    @property
    def key(self) -> tuple[str, str]:
        return ("scipy", "damped_harmonic_oscillator")

    def refinement_options(self, options: Mapping[str, OptionValue]) -> dict[str, OptionValue]:
        refined = dict(options)
        refined["rtol"] = max(float(options["rtol"]) / _REFINEMENT_FACTOR, 1e-14)
        refined["atol"] = max(float(options["atol"]) / _REFINEMENT_FACTOR, 1e-16)
        return refined

    def verify(
        self,
        parameters: Mapping[str, float],
        tolerance: ToleranceSpec,
        primary: RunArrays,
        primary_units: Mapping[str, str],
        replicate: RunArrays,
        refined: RunArrays,
    ) -> VerificationReport:
        m, k, c = parameters["mass"], parameters["stiffness"], parameters["damping"]
        x0, v0 = parameters["initial_displacement"], parameters["initial_velocity"]
        duration = parameters["duration"]
        t = np.asarray(primary["time"])
        x_ref, v_ref = analytic_oscillator(t, m, k, c, x0, v0)
        checks: list[CheckResult] = []

        # 1. Units: declared output units and dimensional consistency of w0.
        ureg = pint.UnitRegistry()
        w0 = ((k * ureg("N/m")) / (m * ureg("kg"))) ** 0.5
        units_ok = dict(primary_units) == _EXPECTED_UNITS and w0.check("1/[time]")
        checks.append(
            CheckResult(
                "units",
                units_ok,
                str(dict(primary_units)),
                str(_EXPECTED_UNITS),
                f"output units declared by engine; sqrt(k/m) has dimension {w0.dimensionality}",
            )
        )

        # 2. Time grid sanity.
        grid_ok = bool(
            t.size >= 2
            and t[0] == 0.0
            and abs(t[-1] - duration) <= 1e-12 * duration
            and np.all(np.diff(t) > 0)
        )
        checks.append(
            CheckResult(
                "time_grid",
                grid_ok,
                float(t[-1]),
                duration,
                "starts at 0, ends at duration, strictly increasing",
            )
        )

        # 3-4. Agreement with the closed-form solution.
        for name, reference in (("displacement", x_ref), ("velocity", v_ref)):
            error = _max_error(primary[name], reference)
            threshold = tolerance.atol + tolerance.rtol * float(np.max(np.abs(reference)))
            checks.append(
                CheckResult(
                    f"{name}_vs_closed_form",
                    error <= threshold,
                    error,
                    threshold,
                    "max |numerical - analytical| <= atol + rtol * max|analytical|",
                )
            )

        # 5. Energy must not increase for c >= 0.
        energy = (
            0.5 * m * np.asarray(primary["velocity"]) ** 2
            + 0.5 * k * np.asarray(primary["displacement"]) ** 2
        )
        rise = float(np.max(np.diff(energy), initial=0.0))
        energy_threshold = tolerance.rtol * float(energy[0]) + tolerance.atol
        checks.append(
            CheckResult(
                "energy_non_increasing",
                rise <= energy_threshold,
                rise,
                energy_threshold,
                "largest step-to-step rise in mechanical energy (J)",
            )
        )

        # 6. Convergence: tightening integrator tolerances must not worsen the error.
        scale = float(np.max(np.abs(x_ref)))
        floor = 1e3 * float(np.finfo(float).eps) * max(scale, 1e-300)
        err_primary = _max_error(primary["displacement"], x_ref)
        err_refined = _max_error(refined["displacement"], x_ref)
        checks.append(
            CheckResult(
                "convergence_under_refinement",
                err_refined <= max(err_primary, floor),
                err_refined,
                max(err_primary, floor),
                f"error with integrator tolerances / {_REFINEMENT_FACTOR:g} "
                f"(primary {err_primary:.3e})",
            )
        )

        # 7. Bitwise reproducibility of an identical re-run.
        same = all(
            float_array_sha256(primary[name]) == float_array_sha256(replicate[name])
            for name in _EXPECTED_UNITS
        )
        checks.append(
            CheckResult(
                "bitwise_reproducibility",
                same,
                "identical" if same else "different",
                "identical",
                "SHA-256 of float64 output columns from an independent re-run",
            )
        )

        return VerificationReport(
            verifier="kobald.supervisor.oscillator.DampedOscillatorVerifier",
            reference="closed-form solution of m x'' + c x' + k x = 0",
            checks=tuple(checks),
            reference_series={
                "time": tuple(float(v) for v in t),
                "displacement": tuple(float(v) for v in x_ref),
                "velocity": tuple(float(v) for v in v_ref),
            },
        )
