"""Model-agnostic provider contract.

Any model (local, cloud, or a future Domovoi model) connects through this
protocol. Providers only produce text/structured proposals. They hold no
reference to the execution gate, sandbox or verifier, so they cannot approve
execution or mark results as verified; proposals they emit enter the system
as requests from a ``PrincipalKind.MODEL`` principal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = ["Message", "ModelIdentity", "ModelProvider", "ModelReply"]


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider: str
    model: str
    version: str


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True, slots=True)
class ModelReply:
    content: str
    identity: ModelIdentity


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def identity(self) -> ModelIdentity: ...

    def complete(self, messages: Sequence[Message], *, max_tokens: int) -> ModelReply: ...
