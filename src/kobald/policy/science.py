"""Scientific execution gate.

A narrow, deny-by-default gate for *computational* experiments only. It is
**not** the WARDEN migration (tracked separately in docs/MIGRATION.md); WARDEN
must later wrap or replace it.

What it enforces:

* Only allow-listed ``(engine, task)`` pairs within policy budget caps run.
* Requests from a ``MODEL`` principal are denied outright unless the policy
  explicitly enables model requests (off by default). When enabled, they need
  an approval that is bound to the exact spec digest, expires, is single-use,
  and carries an HMAC made with a per-gate random key.

Trust assumptions (what the HMAC does and does not prove):

* It stops forgery through **data channels**: a model that can only emit text
  or JSON cannot produce an :class:`Approval` the gate accepts, because it never
  sees the key and the gate accepts only gate-issued ``Approval`` objects.
* It does **not** authenticate humans. :meth:`ScientificExecutionGate.grant`
  trusts the caller's claim that the approver is a human. Any code running in
  the same Python process can call ``grant`` with a self-declared human
  principal or read the key. Real human authentication and out-of-process
  authority are WARDEN's job and are not implemented here.
* The key lives only in memory, so approvals do not survive a restart.
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
    # Model-initiated execution stays disabled until WARDEN/AUDITOR and stronger
    # confinement exist. Only tests of the approval boundary enable it.
    allow_model_requests: bool = False


class ScientificExecutionGate:
    """Evaluates experiment requests against a :class:`ScientificExecutionPolicy`."""

    def __init__(self, policy: ScientificExecutionPolicy) -> None:
        self._policy = policy
        self._key = secrets.token_bytes(32)
        self._consumed: set[str] = set()

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
        if now is not None and now.tzinfo is None:
            raise ApprovalError("approval time must be timezone-aware")
        expires_at = (now or datetime.now(UTC)) + ttl
        digest = spec.digest()
        return Approval(digest, approver, expires_at, self._mac(digest, approver, expires_at))

    def _approval_problem(self, approval: object, digest: str, now: datetime) -> str | None:
        if not isinstance(approval, Approval):
            return "approval is not a gate-issued Approval object"
        try:
            expected = self._mac(approval.spec_digest, approval.approver, approval.expires_at)
        except (AttributeError, TypeError, ValueError):
            return "approval is malformed"
        if not hmac.compare_digest(expected, str(approval.mac)):
            return "approval is not authentic"
        if approval.approver.kind is not PrincipalKind.HUMAN:
            return "approval was not granted by a human"
        if approval.spec_digest != digest:
            return "approval is bound to a different experiment spec"
        if approval.mac in self._consumed:
            return "approval has already been used"
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
        """Decide on a request. An ALLOW that used an approval consumes it."""
        digest = spec.digest()

        def deny(*reasons: str) -> PolicyDecision:
            return PolicyDecision(Decision.DENY, reasons, digest, requester)

        if now is not None and now.tzinfo is None:
            return deny("evaluation time must be timezone-aware")
        now = now or datetime.now(UTC)
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
            return deny(*reasons)

        if requester.kind is PrincipalKind.HUMAN:
            return PolicyDecision(
                Decision.ALLOW,
                ("human-requested allow-listed task within budget",),
                digest,
                requester,
            )
        if not self._policy.allow_model_requests:
            return deny("model-initiated execution is disabled by policy")
        if approval is None:
            return PolicyDecision(
                Decision.REQUIRE_APPROVAL,
                ("model-proposed execution requires human approval",),
                digest,
                requester,
            )
        problem = self._approval_problem(approval, digest, now)
        if problem is not None:
            return deny(problem)
        self._consumed.add(approval.mac)
        until = approval.expires_at.isoformat()
        reason = f"approved by {approval.approver.identifier} until {until} (now consumed)"
        return PolicyDecision(Decision.ALLOW, (reason,), digest, requester)


def allow_tasks(pairs: Iterable[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """Convenience constructor for :attr:`ScientificExecutionPolicy.allowed_tasks`."""
    return frozenset(pairs)
