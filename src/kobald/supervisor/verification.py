"""Independent verification contracts.

Verification verdicts are produced only by supervisor-owned verifiers. Engine
adapters and model providers have no API to create or alter a
:class:`VerificationReport`; a report records which verifier produced it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from kobald.research.spec import OptionValue, ToleranceSpec

__all__ = [
    "CheckResult",
    "ReferenceVerifier",
    "RunArrays",
    "VerificationReport",
    "VerificationStatus",
    "not_verifiable",
]

RunArrays = Mapping[str, tuple[float, ...]]


class VerificationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_VERIFIABLE = "not_verifiable"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    measured: float | str
    threshold: float | str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    verifier: str
    reference: str
    checks: tuple[CheckResult, ...]
    reference_series: RunArrays = field(default_factory=dict)

    @property
    def status(self) -> VerificationStatus:
        if not self.checks:
            return VerificationStatus.NOT_VERIFIABLE
        if all(check.passed for check in self.checks):
            return VerificationStatus.PASSED
        return VerificationStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "verifier": self.verifier,
            "reference": self.reference,
            "checks": [check.to_dict() for check in self.checks],
        }


def not_verifiable(reason: str) -> VerificationReport:
    return VerificationReport(verifier="none", reference=reason, checks=())


class ReferenceVerifier(Protocol):
    """Checks engine output against an independently derived reference."""

    @property
    def key(self) -> tuple[str, str]: ...

    def refinement_options(self, options: Mapping[str, OptionValue]) -> dict[str, OptionValue]: ...

    def verify(
        self,
        parameters: Mapping[str, float],
        tolerance: ToleranceSpec,
        primary: RunArrays,
        primary_units: Mapping[str, str],
        replicate: RunArrays,
        refined: RunArrays,
    ) -> VerificationReport: ...
