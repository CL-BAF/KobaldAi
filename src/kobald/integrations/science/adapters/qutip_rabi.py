"""QuTiP adapter: coherent driving of a two-level system (Rabi oscillation).

Task ``rabi_two_level`` integrates the Schrödinger equation with
``qutip.sesolve`` for the time-independent Hamiltonian (rotating frame,
rotating-wave approximation, hbar = 1)::

    H = (detuning / 2) * sigma_z + (rabi_frequency / 2) * sigma_x

starting from ``|0>`` = ``qutip.basis(2, 0)``, the +1 eigenstate of sigma_z.
Outputs are the populations of ``|0>`` and ``|1>`` and the Bloch components
``<sigma_x>``, ``<sigma_y>``. A constant ``Qobj`` Hamiltonian is used on purpose:
string-based time dependence would trigger Cython compilation.

This adapter contains no analytical solution; the independent reference lives
in :mod:`kobald.supervisor.rabi`.
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

__all__ = ["RABI_TWO_LEVEL", "QutipRabiAdapter"]

_DIMENSIONLESS = "1"

RABI_TWO_LEVEL = TaskDefinition(
    name="rabi_two_level",
    summary="Coherently driven two-level system, H = (Δ/2)sigma_z + (Ω/2)sigma_x, from |0>.",
    parameters=MappingProxyType(
        {
            "rabi_frequency": ParameterRule(
                "rad/s",
                "angular Rabi frequency Ω",
                minimum=0.0,
                minimum_inclusive=False,
                maximum=1e12,
                requires_angle_unit=True,
            ),
            "detuning": ParameterRule(
                "rad/s",
                "angular detuning Δ",
                minimum=-1e12,
                maximum=1e12,
                requires_angle_unit=True,
            ),
            "duration": ParameterRule(
                "s", "evolution time", minimum=0.0, minimum_inclusive=False, maximum=1.0
            ),
        }
    ),
    options=MappingProxyType(
        {
            "method": OptionRule(
                str, "dop853", "sesolve integrator", choices=("dop853", "vern9", "adams", "bdf")
            ),
            "rtol": OptionRule(float, 1e-10, "integrator relative tolerance", None, 1e-14, 1e-3),
            "atol": OptionRule(float, 1e-12, "integrator absolute tolerance", None, 1e-16, 1e-3),
            "nsteps": OptionRule(
                int, 100_000, "max internal steps per output interval", None, 1, 10**7
            ),
            "n_samples": OptionRule(int, 401, "number of output time samples", None, 2, 100_000),
        }
    ),
    outputs=MappingProxyType(
        {
            "time": "s",
            "population_0": _DIMENSIONLESS,
            "population_1": _DIMENSIONLESS,
            "sigma_x": _DIMENSIONLESS,
            "sigma_y": _DIMENSIONLESS,
        }
    ),
)


class QutipRabiAdapter:
    """Adapter exposing QuTiP two-level Rabi dynamics."""

    @property
    def engine_id(self) -> str:
        return "qutip"

    def tasks(self) -> Mapping[str, TaskDefinition]:
        return {RABI_TWO_LEVEL.name: RABI_TWO_LEVEL}

    def run(
        self,
        task: str,
        parameters: Mapping[str, float],
        options: Mapping[str, OptionValue],
        seed: int | None,
    ) -> AdapterResult:
        if task != RABI_TWO_LEVEL.name:
            raise AdapterError(f"unsupported task {task!r}")
        del seed  # deterministic integrator; seed is recorded but unused

        import numpy as np
        import qutip

        omega = parameters["rabi_frequency"]
        delta = parameters["detuning"]
        hamiltonian = 0.5 * delta * qutip.sigmaz() + 0.5 * omega * qutip.sigmax()
        times = np.linspace(0.0, parameters["duration"], int(options["n_samples"]))
        e_ops = [
            qutip.basis(2, 0).proj(),
            qutip.basis(2, 1).proj(),
            qutip.sigmax(),
            qutip.sigmay(),
        ]
        try:
            result = qutip.sesolve(
                hamiltonian,
                qutip.basis(2, 0),
                times,
                e_ops=e_ops,
                options={
                    "method": str(options["method"]),
                    "rtol": float(options["rtol"]),
                    "atol": float(options["atol"]),
                    "nsteps": int(options["nsteps"]),
                    "progress_bar": False,
                },
            )
        except Exception as error:  # QuTiP raises IntegratorException and others
            raise AdapterError(f"qutip.sesolve failed: {type(error).__name__}: {error}") from error

        expectations = [np.asarray(values) for values in result.expect]
        max_imag = max(float(np.max(np.abs(np.imag(values)))) for values in expectations)
        p0, p1, sx, sy = (np.real(values) for values in expectations)

        def column(values: np.ndarray, unit: str = _DIMENSIONLESS) -> OutputColumn:
            return OutputColumn(unit, tuple(float(v) for v in values))

        return AdapterResult(
            engine_version=importlib.metadata.version("qutip"),
            columns={
                "time": column(times, "s"),
                "population_0": column(p0),
                "population_1": column(p1),
                "sigma_x": column(sx),
                "sigma_y": column(sy),
            },
            diagnostics={
                "method": str(options["method"]),
                "max_imaginary_expectation": max_imag,
                "hamiltonian": "0.5*detuning*sigmaz + 0.5*rabi_frequency*sigmax (hbar=1)",
                "initial_state": "basis(2, 0)",
            },
        )
