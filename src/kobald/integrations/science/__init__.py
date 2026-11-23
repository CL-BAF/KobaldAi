"""Scientific engine integrations: catalogue, registry and adapters.

Importing this package never imports a scientific engine.
"""

from kobald.integrations.science.base import (
    AdapterError,
    AdapterResult,
    EngineAdapter,
    OutputColumn,
    TaskDefinition,
)
from kobald.integrations.science.registry import (
    EngineStatus,
    IntegrationLevel,
    ScienceEngineRegistry,
    UnknownEngineTaskError,
    default_registry,
)

__all__ = [
    "AdapterError",
    "AdapterResult",
    "EngineAdapter",
    "EngineStatus",
    "IntegrationLevel",
    "OutputColumn",
    "ScienceEngineRegistry",
    "TaskDefinition",
    "UnknownEngineTaskError",
    "default_registry",
]
