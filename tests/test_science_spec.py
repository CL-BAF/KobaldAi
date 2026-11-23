"""Experiment specification parsing, validation and hashing."""

from __future__ import annotations

import math
from typing import Any

import pytest

from kobald.research.spec import (
    ExperimentSpec,
    QuantitySpec,
    ResourceBudget,
    SpecError,
    ToleranceSpec,
    canonical_json,
)
from tests.conftest import SpecFactory, oscillator_spec_dict


def test_round_trip_and_digest_are_stable(make_spec: SpecFactory) -> None:
    spec = make_spec()
    again = ExperimentSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.digest() == spec.digest()
    assert len(spec.digest()) == 64


def test_digest_changes_with_any_parameter(make_spec: SpecFactory) -> None:
    base = make_spec()
    changed = oscillator_spec_dict()
    changed["parameters"]["mass"] = {"value": 251.0, "unit": "g"}
    assert ExperimentSpec.from_dict(changed).digest() != base.digest()


def test_with_options_returns_new_spec(make_spec: SpecFactory) -> None:
    spec = make_spec()
    refined = spec.with_options(rtol=1e-12)
    assert refined.options["rtol"] == 1e-12
    assert "rtol" not in spec.options
    assert refined.digest() != spec.digest()


def test_defaults_apply_when_optional_sections_are_absent() -> None:
    data = oscillator_spec_dict()
    for key in ("options", "seed", "budget", "tolerance"):
        del data[key]
    spec = ExperimentSpec.from_dict(data)
    assert spec.seed is None
    assert spec.budget == ResourceBudget()
    assert spec.tolerance == ToleranceSpec()


def test_canonical_json_is_sorted_and_rejects_nan() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    with pytest.raises(ValueError):
        canonical_json({"a": math.nan})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"surprise": 1}, "unknown keys"),
        ({"experiment_id": "bad id!"}, "experiment_id"),
        ({"question": "   "}, "question"),
        ({"question": 5}, "question"),
        ({"question": "x" * 2001}, "too long"),
        ({"engine": "SciPy"}, "engine"),
        ({"task": 3}, "task"),
        ({"seed": -1}, "seed"),
        ({"seed": True}, "seed"),
        ({"seed": "1"}, "seed"),
        ({"parameters": []}, "must be an object"),
        ({"parameters": {"Bad": {"value": 1.0, "unit": "m"}}}, "parameter name"),
        ({"parameters": {"x": {"value": "1", "unit": "m"}}}, "number"),
        ({"parameters": {"x": {"value": True, "unit": "m"}}}, "number"),
        ({"parameters": {"x": {"value": math.inf, "unit": "m"}}}, "finite"),
        ({"parameters": {"x": {"value": 1.0, "unit": "m; import os"}}}, "unsupported"),
        ({"parameters": {"x": {"value": 1.0}}}, "missing keys"),
        ({"parameters": {f"p{i}": {"value": 1, "unit": "m"} for i in range(65)}}, "too many"),
        ({"options": {f"o{i}": 1 for i in range(65)}}, "too many options"),
        ({"options": {"Bad": 1}}, "option name"),
        ({"options": {"x": math.nan}}, "finite"),
        ({"options": {"x": [1]}}, "bool, number or string"),
        ({"options": {"x": "y" * 129}}, "too long"),
        ({"budget": {"wall_time_s": 0}}, "wall_time_s"),
        ({"budget": {"memory_mb": 0}}, "memory_mb"),
        ({"budget": {"memory_mb": True}}, "memory_mb"),
        ({"budget": {"max_output_bytes": 1.5}}, "max_output_bytes"),
        ({"budget": {"cpu": 1}}, "unknown keys"),
        ({"tolerance": {"rtol": -1}}, "rtol"),
        ({"tolerance": {"rtol": 0, "atol": 0}}, "at least one"),
    ],
)
def test_invalid_specs_are_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        ExperimentSpec.from_dict(oscillator_spec_dict(**overrides))


def test_non_mapping_spec_is_rejected() -> None:
    with pytest.raises(SpecError, match="must be an object"):
        ExperimentSpec.from_dict([1, 2])


def test_direct_construction_validates_parameter_types() -> None:
    with pytest.raises(SpecError, match="QuantitySpec"):
        ExperimentSpec(
            experiment_id="x",
            question="q",
            engine="scipy",
            task="t",
            parameters={"x": 1.0},  # type: ignore[dict-item]
        )


def test_options_accept_scalars_and_are_frozen(make_spec: SpecFactory) -> None:
    spec = make_spec(options={"a": True, "b": 2, "c": 0.5, "d": "DOP853"})
    assert dict(spec.options) == {"a": True, "b": 2, "c": 0.5, "d": "DOP853"}
    with pytest.raises(TypeError):
        spec.options["a"] = False  # type: ignore[index]


def test_quantity_round_trip() -> None:
    quantity = QuantitySpec(2, "m/s")
    assert QuantitySpec.from_dict(quantity.to_dict()) == QuantitySpec(2.0, "m/s")
