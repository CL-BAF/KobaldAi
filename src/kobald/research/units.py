"""Physical-unit and option validation at the experiment boundary.

Parameters arrive as ``(value, unit)`` pairs. They are parsed with Pint,
checked against the expected physical dimension, range-checked and converted
to SI floats. Engine adapters only ever receive SI magnitudes; the original
units are preserved in the execution record.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pint

from kobald.research.spec import OptionValue, QuantitySpec

__all__ = [
    "NormalizedParameter",
    "OptionRule",
    "ParameterRule",
    "UnitValidationError",
    "dimensionality_of",
    "normalize_parameters",
    "validate_options",
]

_UREG = pint.UnitRegistry()


class UnitValidationError(ValueError):
    """Raised when parameters or options fail validation."""


@dataclass(frozen=True, slots=True)
class ParameterRule:
    """Expected dimension (given by an SI reference unit) and allowed range."""

    si_unit: str
    description: str
    minimum: float | None = None
    minimum_inclusive: bool = True
    maximum: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "si_unit": self.si_unit,
            "dimension": dimensionality_of(self.si_unit),
            "description": self.description,
            "minimum": self.minimum,
            "minimum_inclusive": self.minimum_inclusive,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class OptionRule:
    """Allowed type, default, choices and range for a non-physical option."""

    kind: type[bool] | type[int] | type[float] | type[str]
    default: OptionValue
    description: str
    choices: tuple[OptionValue, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind.__name__,
            "default": self.default,
            "description": self.description,
            "choices": list(self.choices) if self.choices is not None else None,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class NormalizedParameter:
    """A parameter after dimensional validation and SI conversion."""

    name: str
    original: QuantitySpec
    si_value: float
    si_unit: str
    dimension: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original.to_dict(),
            "si_value": self.si_value,
            "si_unit": self.si_unit,
            "dimension": self.dimension,
        }


def dimensionality_of(unit: str) -> str:
    """Human-readable Pint dimensionality, e.g. ``[length] / [time]``."""
    return str(_UREG.parse_units(unit).dimensionality)


def _parse(name: str, quantity: QuantitySpec) -> pint.Quantity:
    try:
        return _UREG.Quantity(quantity.value, quantity.unit)
    except (pint.errors.PintError, AttributeError, TypeError, ValueError) as error:
        raise UnitValidationError(f"{name}: cannot parse unit {quantity.unit!r}") from error


def normalize_parameters(
    parameters: Mapping[str, QuantitySpec], rules: Mapping[str, ParameterRule]
) -> dict[str, NormalizedParameter]:
    """Validate dimensions and ranges, returning SI-normalised parameters."""
    missing = sorted(set(rules) - set(parameters))
    unknown = sorted(set(parameters) - set(rules))
    if missing:
        raise UnitValidationError(f"missing parameters: {missing}")
    if unknown:
        raise UnitValidationError(f"unknown parameters: {unknown}")

    normalized: dict[str, NormalizedParameter] = {}
    for name, rule in rules.items():
        quantity = _parse(name, parameters[name])
        expected = _UREG.parse_units(rule.si_unit)
        if quantity.dimensionality != expected.dimensionality:
            raise UnitValidationError(
                f"{name}: unit {parameters[name].unit!r} has dimension "
                f"{quantity.dimensionality}, expected {expected.dimensionality}"
            )
        si_value = float(quantity.to(expected).magnitude)
        if not math.isfinite(si_value):
            raise UnitValidationError(f"{name}: value is not finite after conversion")
        if rule.minimum is not None and (
            si_value < rule.minimum or (si_value == rule.minimum and not rule.minimum_inclusive)
        ):
            bound = ">=" if rule.minimum_inclusive else ">"
            raise UnitValidationError(f"{name}: must be {bound} {rule.minimum} {rule.si_unit}")
        if rule.maximum is not None and si_value > rule.maximum:
            raise UnitValidationError(f"{name}: must be <= {rule.maximum} {rule.si_unit}")
        normalized[name] = NormalizedParameter(
            name=name,
            original=parameters[name],
            si_value=si_value,
            si_unit=rule.si_unit,
            dimension=str(expected.dimensionality),
        )
    return normalized


def _check_option(name: str, value: OptionValue, rule: OptionRule) -> OptionValue:
    if rule.kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if type(value) is not rule.kind:
        raise UnitValidationError(f"option {name} must be of type {rule.kind.__name__}")
    if rule.choices is not None and value not in rule.choices:
        raise UnitValidationError(f"option {name} must be one of {list(rule.choices)}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if rule.minimum is not None and value < rule.minimum:
            raise UnitValidationError(f"option {name} must be >= {rule.minimum}")
        if rule.maximum is not None and value > rule.maximum:
            raise UnitValidationError(f"option {name} must be <= {rule.maximum}")
    return value


def validate_options(
    options: Mapping[str, OptionValue], rules: Mapping[str, OptionRule]
) -> dict[str, OptionValue]:
    """Reject unknown options, type-check supplied ones and fill defaults."""
    unknown = sorted(set(options) - set(rules))
    if unknown:
        raise UnitValidationError(f"unknown options: {unknown}")
    resolved: dict[str, OptionValue] = {}
    for name, rule in rules.items():
        resolved[name] = _check_option(name, options.get(name, rule.default), rule)
    return resolved
