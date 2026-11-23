"""SciPy adapter: initial-value problems solved with ``scipy.integrate.solve_ivp``.

Task ``damped_harmonic_oscillator`` integrates ``m x'' + c x' + k x = 0``.
This adapter deliberately contains **no** analytical solution: independent
reference checks live in :mod:`kobald.supervisor` and must not import this module.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from types import MappingProxyType

from kobald.integrations.science.base import (
    AdapterError,
    AdapterResult,
    OutputColumn,
    TaskDefinition,
)
from kobald.research.spec import OptionValue
from kobald.research.units import OptionRule, ParameterRule

__all__ = ["DAMPED_OSCILLATOR", "ScipyOdeAdapter"]

DAMPED_OSCILLATOR = TaskDefinition(
    name="damped_harmonic_oscillator",
    summary="Free vibration of a linear mass-spring-damper, m x'' + c x' + k x = 0.",
    parameters=MappingProxyType(
        {
            "mass": ParameterRule("kg", "moving mass m", minimum=0.0, minimum_inclusive=False),
            "stiffness": ParameterRule(
                "N/m", "spring constant k", minimum=0.0, minimum_inclusive=False
            ),
            "damping": ParameterRule("N*s/m", "viscous damping coefficient c", minimum=0.0),
            "initial_displacement": ParameterRule("m", "x(0)"),
            "initial_velocity": ParameterRule("m/s", "x'(0)"),
            "duration": ParameterRule(
                "s", "integration end time", minimum=0.0, minimum_inclusive=False, maximum=1e6
            ),
        }
    ),
    options=MappingProxyType(
        {
            "method": OptionRule(
                str, "DOP853", "solve_ivp integrator", choices=("DOP853", "RK45", "Radau", "LSODA")
            ),
            "rtol": OptionRule(float, 1e-10, "integrator relative tolerance", None, 1e-14, 1e-2),
            "atol": OptionRule(float, 1e-12, "integrator absolute tolerance", None, 1e-16, 1.0),
            "n_samples": OptionRule(int, 2001, "number of output time samples", None, 2, 200_000),
        }
    ),
    outputs=MappingProxyType({"time": "s", "displacement": "m", "velocity": "m/s"}),
)


class ScipyOdeAdapter:
    """Adapter exposing SciPy ODE integration tasks."""

    @property
    def engine_id(self) -> str:
        return "scipy"

    def tasks(self) -> Mapping[str, TaskDefinition]:
        return {DAMPED_OSCILLATOR.name: DAMPED_OSCILLATOR}

    def run(
        self,
        task: str,
        parameters: Mapping[str, float],
        options: Mapping[str, OptionValue],
        seed: int | None,
    ) -> AdapterResult:
        if task != DAMPED_OSCILLATOR.name:
            raise AdapterError(f"unsupported task {task!r}")
        del seed  # deterministic integrator; seed is recorded but unused

        import numpy as np
        from scipy.integrate import solve_ivp

        m = parameters["mass"]
        k = parameters["stiffness"]
        c = parameters["damping"]
        duration = parameters["duration"]

        def rhs(_t: float, y: np.ndarray) -> list[float]:
            return [y[1], -(c * y[1] + k * y[0]) / m]

        t_eval = np.linspace(0.0, duration, int(options["n_samples"]))
        solution = solve_ivp(
            rhs,
            (0.0, duration),
            [parameters["initial_displacement"], parameters["initial_velocity"]],
            method=str(options["method"]),
            t_eval=t_eval,
            rtol=float(options["rtol"]),
            atol=float(options["atol"]),
        )
        if not solution.success:
            raise AdapterError(f"solve_ivp failed: {solution.message}")

        return AdapterResult(
            engine_version=importlib.metadata.version("scipy"),
            columns={
                "time": OutputColumn("s", tuple(float(v) for v in solution.t)),
                "displacement": OutputColumn("m", tuple(float(v) for v in solution.y[0])),
                "velocity": OutputColumn("m/s", tuple(float(v) for v in solution.y[1])),
            },
            diagnostics={
                "method": str(options["method"]),
                "nfev": int(solution.nfev),
                "status": int(solution.status),
            },
        )
