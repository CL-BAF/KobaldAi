"""Shared fixtures for scientific execution tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from kobald.research.spec import ExperimentSpec

SpecFactory = Callable[..., ExperimentSpec]


def oscillator_spec_dict(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "experiment_id": "test-oscillator",
        "question": "Does the integrator match the closed form?",
        "engine": "scipy",
        "task": "damped_harmonic_oscillator",
        "parameters": {
            "mass": {"value": 250.0, "unit": "g"},
            "stiffness": {"value": 40.0, "unit": "N/m"},
            "damping": {"value": 0.316227766, "unit": "kg/s"},
            "initial_displacement": {"value": 5.0, "unit": "cm"},
            "initial_velocity": {"value": 0.0, "unit": "m/s"},
            "duration": {"value": 2.0, "unit": "s"},
        },
        "options": {"n_samples": 401},
        "seed": 0,
        "budget": {"wall_time_s": 60.0, "memory_mb": 1024, "max_output_bytes": 5_000_000},
        "tolerance": {"rtol": 1e-7, "atol": 1e-10},
    }
    data.update(overrides)
    return data


@pytest.fixture
def make_spec() -> SpecFactory:
    def factory(**overrides: Any) -> ExperimentSpec:
        return ExperimentSpec.from_dict(oscillator_spec_dict(**overrides))

    return factory
