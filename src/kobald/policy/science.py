"""Scientific execution gate.

This is a narrow, deny-by-default gate for *computational* experiments only.
It is **not** the WARDEN migration (tracked separately in docs/MIGRATION.md);
WARDEN will later subsume or wrap it.

Guarantees:

* Only allow-listed ``(engine, task)`` pairs can run.
* Requested resource budgets must fit within policy caps.
* Requests from a model principal require an approval granted by a human
  principal, bound to the exact spec digest and an expiry, and authenticated
  with a per-gate secret so that a model cannot forge one.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from kobald.research.spec import ExperimentSpec

__all__ = [
    "Approval",
    "ApprovalError",
    "Decision",
    "PolicyDecision",
    "Principal",
    "PrincipalKind",
    "ScientificExecutionGate",
    "ScientificExecutionPolicy",
]


class ApprovalError(PermissionError):
    """Raised when an approval cannot be granted."""


class PrincipalKind(Enum):
    HUMAN = "human"
    MODEL = "model"


@dataclass(frozen=True, slots=True)
class Principal:
    kind: PrincipalKind
    identifier: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "identifier": self.identifier}


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Decision
    reasons: tuple[str, ...]
    spec_digest: str
    requester: Principal

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "spec_digest": self.spec_digest,
            "requester": self.requester.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Approval:
    spec_digest: str
    approver: Principal
    expires_at: datetime
    mac: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_digest": self.spec_digest,
            "approver": self.approver.to_dict(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ScientificExecutionPolicy:
    allowed_tasks: frozenset[tuple[str, str]]
    max_wall_time_s: float = 300.0
    max_memory_mb: int = 4096
    max_output_bytes: int = 200_000_000
    max_approval_ttl: timedelta = field(default=timedelta(hours=1))


class ScientificExecutionGate:
    """Evaluates experiment requests against a :class:`ScientificExecutionPolicy`."""

    def __init__(self, policy: ScientificExecutionPolicy) -> None:
        self._policy = policy
        self._key = secrets.token_bytes(32)

    @property
    def policy(self) -> ScientificExecutionPolicy:
        return self._policy

    def _mac(self, digest: str, approver: Principal, expires_at: datetime) -> str:
        message = f"{digest}|{approver.kind.value}|{approver.identifier}|{expires_at.isoformat()}"
        return hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def grant(
        self,
        spec: ExperimentSpec,
        approver: Principal,
        ttl: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> Approval:
        """Grant an approval. Only human principals may approve."""
        if approver.kind is not PrincipalKind.HUMAN:
            raise ApprovalError("only a human principal can approve scientific execution")
        if ttl <= timedelta(0) or ttl > self._policy.max_approval_ttl:
            raise ApprovalError("approval lifetime is outside the permitted range")
        expires_at = (now or datetime.now(UTC)) + ttl
        digest = spec.digest()
        return Approval(digest, approver, expires_at, self._mac(digest, approver, expires_at))

    def _approval_problem(self, approval: Approval, digest: str, now: datetime) -> str | None:
        expected = self._mac(approval.spec_digest, approval.approver, approval.expires_at)
        if not hmac.compare_digest(expected, approval.mac):
            return "approval is not authentic"
        if approval.approver.kind is not PrincipalKind.HUMAN:
            return "approval was not granted by a human"
        if approval.spec_digest != digest:
            return "approval is bound to a different experiment spec"
        if now >= approval.expires_at:
            return "approval has expired"
        return None

    def evaluate(
        self,
        spec: ExperimentSpec,
        requester: Principal,
        approval: Approval | None = None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        digest = spec.digest()
        reasons: list[str] = []
        if (spec.engine, spec.task) not in self._policy.allowed_tasks:
            reasons.append(f"engine task {spec.engine}/{spec.task} is not allow-listed")
        if spec.budget.wall_time_s > self._policy.max_wall_time_s:
            reasons.append("requested wall time exceeds policy cap")
        if spec.budget.memory_mb > self._policy.max_memory_mb:
            reasons.append("requested memory exceeds policy cap")
        if spec.budget.max_output_bytes > self._policy.max_output_bytes:
            reasons.append("requested output size exceeds policy cap")
        if reasons:
            return PolicyDecision(Decision.DENY, tuple(reasons), digest, requester)

        if requester.kind is PrincipalKind.HUMAN:
            return PolicyDecision(
                Decision.ALLOW,
                ("human-requested allow-listed task within budget",),
                digest,
                requester,
            )
        if approval is None:
            return PolicyDecision(
                Decision.REQUIRE_APPROVAL,
                ("model-proposed execution requires human approval",),
                digest,
                requester,
            )
        problem = self._approval_problem(approval, digest, now or datetime.now(UTC))
        if problem is not None:
            return PolicyDecision(Decision.DENY, (problem,), digest, requester)
        until = approval.expires_at.isoformat()
        reason = f"approved by {approval.approver.identifier} until {until}"
        return PolicyDecision(Decision.ALLOW, (reason,), digest, requester)


def allow_tasks(pairs: Iterable[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """Convenience constructor for :attr:`ScientificExecutionPolicy.allowed_tasks`."""
    return frozenset(pairs)
