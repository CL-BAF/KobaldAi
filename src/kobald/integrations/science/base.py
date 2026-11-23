"""Standard contract every scientific engine adapter implements."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from kobald.research.spec import OptionValue
from kobald.research.units import OptionRule, ParameterRule

__all__ = [
    "AdapterError",
    "AdapterResult",
    "EngineAdapter",
    "OutputColumn",
    "TaskDefinition",
]


class AdapterError(RuntimeError):
    """Raised by an adapter when the engine cannot complete the task."""


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    """A computational task an adapter exposes, with its input contract."""

    name: str
    summary: str
    parameters: Mapping[str, ParameterRule]
    options: Mapping[str, OptionRule]
    outputs: Mapping[str, str]  # output column/scalar name -> SI unit

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "options": {k: v.to_dict() for k, v in self.options.items()},
            "outputs": dict(self.outputs),
        }


@dataclass(frozen=True, slots=True)
class OutputColumn:
    """One column of a tabular numerical result."""

    unit: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in self.values):
            raise AdapterError("output column contains non-finite values")


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Raw engine output. Interpretation and verification happen elsewhere."""

    engine_version: str
    columns: Mapping[str, OutputColumn]
    scalars: Mapping[str, tuple[float, str]] = field(default_factory=dict)
    diagnostics: Mapping[str, OptionValue] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        lengths = {len(column.values) for column in self.columns.values()}
        if len(lengths) > 1:
            raise AdapterError("output columns have different lengths")


@runtime_checkable
class EngineAdapter(Protocol):
    """Adapters translate SI-normalised parameters into engine calls.

    Adapters must not perform policy decisions, mark results as verified, or
    access the network. They run inside the sandbox worker process.
    """

    @property
    def engine_id(self) -> str: ...

    def tasks(self) -> Mapping[str, TaskDefinition]: ...

    def run(
        self,
        task: str,
        parameters: Mapping[str, float],
        options: Mapping[str, OptionValue],
        seed: int | None,
    ) -> AdapterResult: ...
