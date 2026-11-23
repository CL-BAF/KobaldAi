"""Physical-unit validation and option checking."""

from __future__ import annotations

import pytest

from kobald.research.spec import OptionValue, QuantitySpec
from kobald.research.units import (
    OptionRule,
    ParameterRule,
    UnitValidationError,
    dimensionality_of,
    normalize_parameters,
    validate_options,
)

RULES = {
    "length": ParameterRule("m", "a length", minimum=0.0, minimum_inclusive=False, maximum=10.0),
    "speed": ParameterRule("m/s", "a speed", minimum=0.0),
    "force": ParameterRule("N", "unbounded"),
}


def params(**overrides: QuantitySpec) -> dict[str, QuantitySpec]:
    base = {
        "length": QuantitySpec(150.0, "cm"),
        "speed": QuantitySpec(36.0, "km/hour"),
        "force": QuantitySpec(-2.0, "kN"),
    }
    base.update(overrides)
    return base


def test_converts_to_si_and_records_original() -> None:
    result = normalize_parameters(params(), RULES)
    assert result["length"].si_value == pytest.approx(1.5)
    assert result["speed"].si_value == pytest.approx(10.0)
    assert result["force"].si_value == pytest.approx(-2000.0)
    assert result["length"].original == QuantitySpec(150.0, "cm")
    as_dict = result["speed"].to_dict()
    assert as_dict["si_unit"] == "m/s"
    assert as_dict["dimension"] == "[length] / [time]"


def test_equivalent_units_are_accepted() -> None:
    result = normalize_parameters(params(force=QuantitySpec(3.0, "kg*m/s**2")), RULES)
    assert result["force"].si_value == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"length": QuantitySpec(1.0, "s")}, "expected"),
        ({"speed": QuantitySpec(1.0, "m")}, "dimension"),
        ({"length": QuantitySpec(1.0, "furlongz")}, "cannot parse"),
        ({"length": QuantitySpec(1.0, "m)")}, "cannot parse"),
        ({"length": QuantitySpec(0.0, "m")}, "must be >"),
        ({"length": QuantitySpec(-1.0, "m")}, "must be >"),
        ({"length": QuantitySpec(11.0, "m")}, "must be <="),
        ({"speed": QuantitySpec(-1.0, "m/s")}, "must be >="),
        ({"force": QuantitySpec(1e308, "kN")}, "not finite"),
    ],
)
def test_invalid_quantities_are_rejected(overrides: dict[str, QuantitySpec], message: str) -> None:
    with pytest.raises(UnitValidationError, match=message):
        normalize_parameters(params(**overrides), RULES)


def test_inclusive_minimum_allows_boundary() -> None:
    assert (
        normalize_parameters(params(speed=QuantitySpec(0.0, "m/s")), RULES)["speed"].si_value == 0
    )


def test_missing_and_unknown_parameters_are_rejected() -> None:
    reduced = params()
    del reduced["force"]
    with pytest.raises(UnitValidationError, match="missing"):
        normalize_parameters(reduced, RULES)
    with pytest.raises(UnitValidationError, match="unknown"):
        normalize_parameters(params(extra=QuantitySpec(1.0, "m")), RULES)


def test_rule_serialisation() -> None:
    assert RULES["length"].to_dict()["dimension"] == "[length]"
    assert dimensionality_of("N*s/m") == "[mass] / [time]"


OPTION_RULES = {
    "method": OptionRule(str, "A", "solver", choices=("A", "B")),
    "rtol": OptionRule(float, 1e-6, "tolerance", minimum=1e-12, maximum=1e-2),
    "count": OptionRule(int, 10, "count"),
    "flag": OptionRule(bool, False, "flag"),
}


def test_options_fill_defaults_and_coerce_ints_to_floats() -> None:
    resolved = validate_options(
        {"rtol": 1, "flag": True},
        {**OPTION_RULES, "rtol": OptionRule(float, 1e-6, "tolerance", maximum=2.0)},
    )
    assert resolved == {"method": "A", "rtol": 1.0, "count": 10, "flag": True}
    assert type(resolved["rtol"]) is float


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"nope": 1}, "unknown options"),
        ({"method": "C"}, "one of"),
        ({"method": 1}, "type str"),
        ({"count": 1.5}, "type int"),
        ({"count": True}, "type int"),
        ({"flag": 1}, "type bool"),
        ({"rtol": 1e-20}, ">="),
        ({"rtol": 0.5}, "<="),
    ],
)
def test_invalid_options_are_rejected(options: dict[str, OptionValue], message: str) -> None:
    with pytest.raises(UnitValidationError, match=message):
        validate_options(options, OPTION_RULES)


def test_option_rule_serialisation() -> None:
    assert OPTION_RULES["method"].to_dict()["choices"] == ["A", "B"]
    assert OPTION_RULES["count"].to_dict() == {
        "type": "int",
        "default": 10,
        "description": "count",
        "choices": None,
        "minimum": None,
        "maximum": None,
    }
