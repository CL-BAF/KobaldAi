"""Engine registry: joins the engine catalogue with the adapters that drive them."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from kobald.integrations.science.base import EngineAdapter, TaskDefinition
from kobald.integrations.science.catalog import (
    ENGINE_CATALOG,
    EngineDescriptor,
    EngineProbe,
    probe_engine,
)

__all__ = [
    "EngineStatus",
    "IntegrationLevel",
    "ScienceEngineRegistry",
    "UnknownEngineTaskError",
    "default_registry",
]


class UnknownEngineTaskError(LookupError):
    """Raised when no registered adapter provides the requested engine task."""


class IntegrationLevel(Enum):
    ADAPTER_READY = "adapter_ready"  # engine installed and an adapter is registered
    ADAPTER_ENGINE_MISSING = "adapter_engine_missing"
    DETECTED_NO_ADAPTER = "detected_no_adapter"
    NOT_INSTALLED = "not_installed"


@dataclass(frozen=True, slots=True)
class EngineStatus:
    descriptor: EngineDescriptor
    probe: EngineProbe
    tasks: tuple[str, ...]

    @property
    def level(self) -> IntegrationLevel:
        if self.tasks:
            if self.probe.installed:
                return IntegrationLevel.ADAPTER_READY
            return IntegrationLevel.ADAPTER_ENGINE_MISSING
        if self.probe.installed:
            return IntegrationLevel.DETECTED_NO_ADAPTER
        return IntegrationLevel.NOT_INSTALLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.descriptor.engine_id,
            "name": self.descriptor.display_name,
            "domain": self.descriptor.domain,
            "kind": self.descriptor.kind.value,
            "installed": self.probe.installed,
            "version": self.probe.version,
            "tasks": list(self.tasks),
            "level": self.level.value,
            "needs_isolated_linux_env": self.descriptor.needs_isolated_linux_env,
            "install_extra": self.descriptor.install_extra,
            "notes": self.descriptor.notes,
        }


class ScienceEngineRegistry:
    """Discovers engines and resolves ``(engine, task)`` pairs to adapters."""

    def __init__(
        self,
        catalog: Iterable[EngineDescriptor] = ENGINE_CATALOG,
        adapters: Iterable[EngineAdapter] = (),
    ) -> None:
        self._catalog = {d.engine_id: d for d in catalog}
        self._adapters: dict[str, EngineAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: EngineAdapter) -> None:
        if adapter.engine_id not in self._catalog:
            raise ValueError(f"engine {adapter.engine_id!r} is not in the catalogue")
        if adapter.engine_id in self._adapters:
            raise ValueError(f"an adapter for {adapter.engine_id!r} is already registered")
        self._adapters[adapter.engine_id] = adapter

    def descriptor(self, engine_id: str) -> EngineDescriptor:
        try:
            return self._catalog[engine_id]
        except KeyError:
            raise UnknownEngineTaskError(f"unknown engine {engine_id!r}") from None

    def resolve(self, engine_id: str, task: str) -> tuple[EngineAdapter, TaskDefinition]:
        self.descriptor(engine_id)
        adapter = self._adapters.get(engine_id)
        if adapter is None:
            raise UnknownEngineTaskError(f"no adapter is registered for engine {engine_id!r}")
        definition = adapter.tasks().get(task)
        if definition is None:
            raise UnknownEngineTaskError(f"engine {engine_id!r} has no task {task!r}")
        return adapter, definition

    def tasks(self) -> Mapping[tuple[str, str], TaskDefinition]:
        return {
            (engine_id, name): definition
            for engine_id, adapter in self._adapters.items()
            for name, definition in adapter.tasks().items()
        }

    def discover(self, which: Callable[[str], str | None] = shutil.which) -> list[EngineStatus]:
        statuses = []
        for engine_id, descriptor in self._catalog.items():
            adapter = self._adapters.get(engine_id)
            tasks = tuple(sorted(adapter.tasks())) if adapter is not None else ()
            statuses.append(EngineStatus(descriptor, probe_engine(descriptor, which), tasks))
        return statuses


def default_registry() -> ScienceEngineRegistry:
    """Registry with every adapter shipped in this package."""
    from kobald.integrations.science.adapters.qutip_rabi import QutipRabiAdapter
    from kobald.integrations.science.adapters.scipy_ode import ScipyOdeAdapter

    return ScienceEngineRegistry(adapters=[ScipyOdeAdapter(), QutipRabiAdapter()])
