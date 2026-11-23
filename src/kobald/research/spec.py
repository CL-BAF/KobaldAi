"""Typed, hashable specifications for computational experiments.

An :class:`ExperimentSpec` is the single structured object that a human or a
model submits. It is treated as untrusted input: :meth:`ExperimentSpec.from_dict`
rejects unknown keys, non-finite numbers and malformed identifiers. The
canonical digest binds approvals and execution records to the exact request.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = [
    "SPEC_SCHEMA_VERSION",
    "ExperimentSpec",
    "OptionValue",
    "QuantitySpec",
    "ResourceBudget",
    "SpecError",
    "ToleranceSpec",
    "canonical_json",
]

SPEC_SCHEMA_VERSION = 1

OptionValue = bool | int | float | str

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_UNIT_TEXT = re.compile(r"^[A-Za-z0-9_ */^().\-]{1,64}$")
_MAX_QUESTION_LENGTH = 2000
_MAX_PARAMETERS = 64


class SpecError(ValueError):
    """Raised when an experiment specification is structurally invalid."""


def canonical_json(value: Any) -> str:
    """Serialise ``value`` deterministically for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _require_finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise SpecError(f"{name} must be finite")
    return number


def _require_identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SpecError(f"{name} must match {_IDENTIFIER.pattern}")
    return value


def _require_keys(
    name: str, data: Mapping[str, Any], required: set[str], optional: set[str]
) -> None:
    keys = set(data)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise SpecError(f"{name} is missing keys: {sorted(missing)}")
    if unknown:
        raise SpecError(f"{name} has unknown keys: {sorted(unknown)}")


def _require_mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(f"{name} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class QuantitySpec:
    """A numeric value with an explicit unit string (parsed later by Pint)."""

    value: float
    unit: str

    def __post_init__(self) -> None:
        _require_finite("quantity value", self.value)
        if not isinstance(self.unit, str) or not _UNIT_TEXT.fullmatch(self.unit):
            raise SpecError(f"unit {self.unit!r} contains unsupported characters")

    def to_dict(self) -> dict[str, Any]:
        return {"value": float(self.value), "unit": self.unit}

    @classmethod
    def from_dict(cls, data: object) -> QuantitySpec:
        mapping = _require_mapping("quantity", data)
        _require_keys("quantity", mapping, {"value", "unit"}, set())
        return cls(value=_require_finite("quantity value", mapping["value"]), unit=mapping["unit"])


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """Resources requested for one execution. Policy may cap these further."""

    wall_time_s: float = 60.0
    memory_mb: int = 1024
    max_output_bytes: int = 50_000_000

    def __post_init__(self) -> None:
        if _require_finite("wall_time_s", self.wall_time_s) <= 0:
            raise SpecError("wall_time_s must be positive")
        for name in ("memory_mb", "max_output_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpecError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_time_s": float(self.wall_time_s),
            "memory_mb": self.memory_mb,
            "max_output_bytes": self.max_output_bytes,
        }

    @classmethod
    def from_dict(cls, data: object) -> ResourceBudget:
        mapping = _require_mapping("budget", data)
        _require_keys("budget", mapping, set(), {"wall_time_s", "memory_mb", "max_output_bytes"})
        return cls(**mapping)


@dataclass(frozen=True, slots=True)
class ToleranceSpec:
    """Acceptance tolerance used by independent verification: |err| <= atol + rtol*scale."""

    rtol: float = 1e-6
    atol: float = 1e-9

    def __post_init__(self) -> None:
        for name in ("rtol", "atol"):
            if _require_finite(name, getattr(self, name)) < 0:
                raise SpecError(f"{name} must be non-negative")
        if self.rtol == 0 and self.atol == 0:
            raise SpecError("at least one of rtol or atol must be positive")

    def to_dict(self) -> dict[str, float]:
        return {"rtol": float(self.rtol), "atol": float(self.atol)}

    @classmethod
    def from_dict(cls, data: object) -> ToleranceSpec:
        mapping = _require_mapping("tolerance", data)
        _require_keys("tolerance", mapping, set(), {"rtol", "atol"})
        return cls(**mapping)


def _freeze_parameters(parameters: Mapping[str, QuantitySpec]) -> Mapping[str, QuantitySpec]:
    if len(parameters) > _MAX_PARAMETERS:
        raise SpecError("too many parameters")
    for name, quantity in parameters.items():
        _require_identifier("parameter name", name)
        if not isinstance(quantity, QuantitySpec):
            raise SpecError(f"parameter {name} must be a QuantitySpec")
    return MappingProxyType(dict(sorted(parameters.items())))


def _freeze_options(options: Mapping[str, OptionValue]) -> Mapping[str, OptionValue]:
    if len(options) > _MAX_PARAMETERS:
        raise SpecError("too many options")
    for name, value in options.items():
        _require_identifier("option name", name)
        if isinstance(value, float):
            _require_finite(f"option {name}", value)
        elif not isinstance(value, bool | int | str):
            raise SpecError(f"option {name} must be a bool, number or string")
        elif isinstance(value, str) and len(value) > 128:
            raise SpecError(f"option {name} is too long")
    return MappingProxyType(dict(sorted(options.items())))


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """A complete, self-describing computational experiment request."""

    experiment_id: str
    question: str
    engine: str
    task: str
    parameters: Mapping[str, QuantitySpec]
    options: Mapping[str, OptionValue] = field(default_factory=dict)
    seed: int | None = None
    budget: ResourceBudget = field(default_factory=ResourceBudget)
    tolerance: ToleranceSpec = field(default_factory=ToleranceSpec)

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or not _EXPERIMENT_ID.fullmatch(
            self.experiment_id
        ):
            raise SpecError(f"experiment_id must match {_EXPERIMENT_ID.pattern}")
        if not isinstance(self.question, str) or not self.question.strip():
            raise SpecError("question must be a non-empty string")
        if len(self.question) > _MAX_QUESTION_LENGTH:
            raise SpecError("question is too long")
        _require_identifier("engine", self.engine)
        _require_identifier("task", self.task)
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0
        ):
            raise SpecError("seed must be a non-negative integer or null")
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))
        object.__setattr__(self, "options", _freeze_options(self.options))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SPEC_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "question": self.question,
            "engine": self.engine,
            "task": self.task,
            "parameters": {name: q.to_dict() for name, q in self.parameters.items()},
            "options": dict(self.options),
            "seed": self.seed,
            "budget": self.budget.to_dict(),
            "tolerance": self.tolerance.to_dict(),
        }

    def digest(self) -> str:
        """SHA-256 of the canonical JSON form; binds approvals and records."""
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def with_options(self, **overrides: OptionValue) -> ExperimentSpec:
        """Return a copy with selected options replaced (used for refinement runs)."""
        merged = dict(self.options)
        merged.update(overrides)
        return ExperimentSpec(
            experiment_id=self.experiment_id,
            question=self.question,
            engine=self.engine,
            task=self.task,
            parameters=self.parameters,
            options=merged,
            seed=self.seed,
            budget=self.budget,
            tolerance=self.tolerance,
        )

    @classmethod
    def from_dict(cls, data: object) -> ExperimentSpec:
        mapping = _require_mapping("experiment spec", data)
        _require_keys(
            "experiment spec",
            mapping,
            {"experiment_id", "question", "engine", "task", "parameters"},
            {"schema_version", "options", "seed", "budget", "tolerance"},
        )
        version = mapping.get("schema_version", SPEC_SCHEMA_VERSION)
        if version != SPEC_SCHEMA_VERSION:
            raise SpecError(f"unsupported schema_version {version!r}")
        parameters = {
            name: QuantitySpec.from_dict(value)
            for name, value in _require_mapping("parameters", mapping["parameters"]).items()
        }
        return cls(
            experiment_id=mapping["experiment_id"],
            question=mapping["question"],
            engine=mapping["engine"],
            task=mapping["task"],
            parameters=parameters,
            options=dict(_require_mapping("options", mapping.get("options", {}))),
            seed=mapping.get("seed"),
            budget=ResourceBudget.from_dict(mapping.get("budget", {})),
            tolerance=ToleranceSpec.from_dict(mapping.get("tolerance", {})),
        )
