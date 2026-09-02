"""Stable project identity used by interfaces and diagnostics."""

from dataclasses import dataclass

__all__ = ["PROJECT", "ProjectInfo"]


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """Human-readable identity for this implementation."""

    name: str
    repository: str
    canonical: bool


PROJECT = ProjectInfo(
    name="KobaldAi",
    repository="https://github.com/CL-BAF/KobaldAi",
    canonical=True,
)
