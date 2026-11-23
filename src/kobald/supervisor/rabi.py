"""Independent closed-form reference for a driven two-level system.

For ``H = (Δ/2)sigma_z + (Ω/2)sigma_x`` (hbar = 1) the Bloch vector precesses about
``n = (Ω, 0, Δ) / W`` with generalised Rabi frequency ``W = sqrt(Ω² + Δ²)``.
Starting from ``|0>`` (Bloch vector (0, 0, 1))::

    <sigma_x>(t) = (ΔΩ / W²) (1 - cos Wt)
    <sigma_y>(t) = -(Ω / W) sin Wt
    <sigma_z>(t) = (Δ² + Ω² cos Wt) / W²
    P1(t)   = (Ω² / W²) sin²(Wt / 2)      (the Rabi formula)
    P0(t)   = 1 - P1(t)

This module must not import QuTiP or any adapter (enforced by a test).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pint

from kobald.research.hashing import float_array_sha256
from kobald.research.spec import OptionValue, ToleranceSpec
from kobald.supervisor.verification import CheckResult, RunArrays, VerificationReport

__all__ = ["RabiVerifier", "analytic_rabi"]

_EXPECTED_UNITS = {
    "time": "s",
    "population_0": "1",
    "population_1": "1",
    "sigma_x": "1",
    "sigma_y": "1",
}
_REFINEMENT_FACTOR = 100.0


def analytic_rabi(t: np.ndarray, omega: float, delta: float) -> dict[str, np.ndarray]:
    """Closed-form populations and Bloch components for the state starting in |0>."""
    w = np.hypot(omega, delta)
    cos = np.cos(w * t)
    p1 = (omega / w) ** 2 * np.sin(0.5 * w * t) ** 2
    return {
        "population_0": 1.0 - p1,
        "population_1": p1,
        "sigma_x": (delta * omega / w**2) * (1.0 - cos),
        "sigma_y": -(omega / w) * np.sin(w * t),
    }


def _max_abs(values: tuple[float, ...], reference: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(values) - reference)))


class RabiVerifier:
    """Verifies ``qutip/rabi_two_level`` against the closed-form Bloch solution."""

    @property
    def key(self) -> tuple[str, str]:
        return ("qutip", "rabi_two_level")

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
        omega, delta = parameters["rabi_frequency"], parameters["detuning"]
        duration = parameters["duration"]
        t = np.asarray(primary["time"])
        reference = analytic_rabi(t, omega, delta)
        # All observables are bounded by 1, so the absolute threshold uses scale 1.
        threshold = tolerance.atol + tolerance.rtol
        checks: list[CheckResult] = []

        ureg = pint.UnitRegistry()
        w_t = (omega * ureg("rad/s")) * (duration * ureg("s"))
        units_ok = dict(primary_units) == _EXPECTED_UNITS and w_t.dimensionless
        checks.append(
            CheckResult(
                "units",
                units_ok,
                str(dict(primary_units)),
                str(_EXPECTED_UNITS),
                "declared output units; Ω·t must be dimensionless (radians)",
            )
        )

        grid_ok = bool(
            t.size >= 2
            and t[0] == 0.0
            and abs(t[-1] - duration) <= 1e-12 * duration
            and np.all(np.diff(t) > 0)
        )
        checks.append(
            CheckResult(
                "time_grid", grid_ok, float(t[-1]), duration, "starts at 0, ends at duration"
            )
        )

        for name in ("population_1", "population_0", "sigma_x", "sigma_y"):
            error = _max_abs(primary[name], reference[name])
            checks.append(
                CheckResult(
                    f"{name}_vs_closed_form",
                    error <= threshold,
                    error,
                    threshold,
                    "max |numerical - analytical|",
                )
            )

        p0, p1 = np.asarray(primary["population_0"]), np.asarray(primary["population_1"])
        norm_error = float(np.max(np.abs(p0 + p1 - 1.0)))
        checks.append(
            CheckResult(
                "probability_conservation",
                norm_error <= threshold,
                norm_error,
                threshold,
                "max |P0 + P1 - 1|",
            )
        )
        sz = p0 - p1
        sx, sy = np.asarray(primary["sigma_x"]), np.asarray(primary["sigma_y"])
        purity_error = float(np.max(np.abs(np.sqrt(sx**2 + sy**2 + sz**2) - 1.0)))
        checks.append(
            CheckResult(
                "bloch_vector_unit_length",
                purity_error <= threshold,
                purity_error,
                threshold,
                "pure-state evolution keeps |r| = 1",
            )
        )
        out_of_bounds = float(max(np.max(-p1), np.max(p1 - 1.0), 0.0))
        checks.append(
            CheckResult(
                "population_bounds",
                out_of_bounds <= threshold,
                out_of_bounds,
                threshold,
                "populations stay within [0, 1]",
            )
        )

        floor = 1e3 * float(np.finfo(float).eps)
        err_primary = _max_abs(primary["population_1"], reference["population_1"])
        err_refined = _max_abs(refined["population_1"], reference["population_1"])
        checks.append(
            CheckResult(
                "convergence_under_refinement",
                err_refined <= max(err_primary, floor),
                err_refined,
                max(err_primary, floor),
                f"P1 error with integrator tolerances / {_REFINEMENT_FACTOR:g} "
                f"(primary {err_primary:.3e})",
            )
        )

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
            verifier="kobald.supervisor.rabi.RabiVerifier",
            reference="closed-form Bloch-vector solution of H = (Δ/2)sigma_z + (Ω/2)sigma_x",
            checks=tuple(checks),
            reference_series={"time": tuple(float(v) for v in t)}
            | {name: tuple(float(v) for v in values) for name, values in reference.items()},
        )
