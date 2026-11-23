"""Scientific execution gate: deny-by-default, budgets and the approval boundary.

Negative security tests document exactly what the gate's approval mechanism
enforces. The trust assumptions are stated in ``kobald.policy.science``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from kobald.policy.science import (
    Approval,
    ApprovalError,
    Decision,
    Principal,
    PrincipalKind,
    ScientificExecutionGate,
    ScientificExecutionPolicy,
    allow_tasks,
)
from tests.conftest import SpecFactory

HUMAN = Principal(PrincipalKind.HUMAN, "researcher")
MODEL = Principal(PrincipalKind.MODEL, "some-model")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
TASKS = allow_tasks([("scipy", "damped_harmonic_oscillator")])


def _gate(allow_model_requests: bool = True) -> ScientificExecutionGate:
    return ScientificExecutionGate(
        ScientificExecutionPolicy(
            allowed_tasks=TASKS,
            max_wall_time_s=100.0,
            max_memory_mb=2048,
            max_output_bytes=10_000_000,
            allow_model_requests=allow_model_requests,
        )
    )


@pytest.fixture
def gate() -> ScientificExecutionGate:
    """A gate with model requests enabled, to exercise the approval boundary."""
    return _gate()


# --- basic policy -------------------------------------------------------------------


def test_human_request_within_policy_is_allowed(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    decision = gate.evaluate(make_spec(), HUMAN)
    assert decision.allowed and decision.decision is Decision.ALLOW
    assert decision.to_dict()["requester"] == {"kind": "human", "identifier": "researcher"}
    assert gate.policy.max_memory_mb == 2048


def test_unlisted_task_is_denied_even_for_humans(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    decision = gate.evaluate(make_spec(task="other_task"), HUMAN)
    assert decision.decision is Decision.DENY
    assert "not allow-listed" in decision.reasons[0]


def test_every_exceeded_budget_is_reported(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec(budget={"wall_time_s": 101, "memory_mb": 4096, "max_output_bytes": 10**9})
    decision = gate.evaluate(spec, HUMAN)
    assert decision.decision is Decision.DENY
    assert len(decision.reasons) == 3


def test_model_requests_are_disabled_by_default(make_spec: SpecFactory) -> None:
    default_gate = ScientificExecutionGate(ScientificExecutionPolicy(allowed_tasks=TASKS))
    spec = make_spec()
    approval = default_gate.grant(spec, HUMAN, now=NOW)
    for supplied in (None, approval):
        decision = default_gate.evaluate(spec, MODEL, supplied, now=NOW)
        assert decision.decision is Decision.DENY
        assert decision.reasons == ("model-initiated execution is disabled by policy",)


def test_model_request_requires_and_accepts_human_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    assert gate.evaluate(spec, MODEL).decision is Decision.REQUIRE_APPROVAL
    approval = gate.grant(spec, HUMAN, now=NOW)
    decision = gate.evaluate(spec, MODEL, approval, now=NOW + timedelta(minutes=1))
    assert decision.allowed
    assert "consumed" in decision.reasons[0]
    assert approval.to_dict()["approver"]["kind"] == "human"


def test_policy_denial_takes_precedence_over_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec(budget={"wall_time_s": 500})
    approval = gate.grant(spec, HUMAN, now=NOW)
    assert gate.evaluate(spec, MODEL, approval, now=NOW).decision is Decision.DENY


# --- grant() constraints ------------------------------------------------------------


def test_model_cannot_grant_approval(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    with pytest.raises(ApprovalError, match="only a human"):
        gate.grant(make_spec(), MODEL)


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1), timedelta(hours=2)])
def test_approval_lifetime_is_bounded(
    gate: ScientificExecutionGate, make_spec: SpecFactory, ttl: timedelta
) -> None:
    with pytest.raises(ApprovalError, match="lifetime"):
        gate.grant(make_spec(), HUMAN, ttl=ttl)


def test_grant_rejects_naive_time(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    with pytest.raises(ApprovalError, match="timezone-aware"):
        gate.grant(make_spec(), HUMAN, now=datetime(2026, 1, 1))


# --- negative security tests: data-channel forgery and misuse -----------------------


def test_forged_mac_is_denied(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    spec = make_spec()
    forged = Approval(spec.digest(), HUMAN, NOW + timedelta(minutes=5), mac="0" * 64)
    decision = gate.evaluate(spec, MODEL, forged, now=NOW)
    assert decision.decision is Decision.DENY
    assert decision.reasons == ("approval is not authentic",)


@pytest.mark.parametrize(
    "tamper",
    [
        {"spec_digest": "f" * 64},
        {"approver": Principal(PrincipalKind.HUMAN, "someone-else")},
        {"approver": MODEL},
        {"expires_at": NOW + timedelta(days=365)},
        {"mac": "a" * 64},
    ],
    ids=["digest", "approver-id", "approver-kind", "expiry", "mac"],
)
def test_every_single_field_tamper_is_denied(
    gate: ScientificExecutionGate, make_spec: SpecFactory, tamper: dict[str, Any]
) -> None:
    spec = make_spec()
    approval = dataclasses.replace(gate.grant(spec, HUMAN, now=NOW), **tamper)
    decision = gate.evaluate(spec, MODEL, approval, now=NOW)
    assert decision.decision is Decision.DENY
    assert decision.reasons == ("approval is not authentic",)


@pytest.mark.parametrize(
    "supplied",
    [
        {"spec_digest": "x", "approver": {"kind": "human"}, "mac": "0" * 64},
        "approved",
        42,
    ],
    ids=["model-json", "string", "number"],
)
def test_non_approval_objects_fail_closed(
    gate: ScientificExecutionGate, make_spec: SpecFactory, supplied: Any
) -> None:
    decision = gate.evaluate(make_spec(), MODEL, supplied, now=NOW)
    assert decision.decision is Decision.DENY
    assert decision.reasons == ("approval is not a gate-issued Approval object",)


def test_malformed_approval_fields_fail_closed(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    broken = Approval(spec.digest(), "human", NOW, "0" * 64)  # type: ignore[arg-type]
    decision = gate.evaluate(spec, MODEL, broken, now=NOW)
    assert decision.reasons == ("approval is malformed",)


def test_naive_evaluation_time_fails_closed(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, now=NOW)
    decision = gate.evaluate(spec, MODEL, approval, now=datetime(2026, 1, 1))
    assert decision.reasons == ("evaluation time must be timezone-aware",)


def test_approval_from_another_gate_is_not_authentic(make_spec: SpecFactory) -> None:
    spec = make_spec()
    approval = _gate().grant(spec, HUMAN, now=NOW)
    decision = _gate().evaluate(spec, MODEL, approval, now=NOW)
    assert decision.reasons == ("approval is not authentic",)


def test_correctly_macd_non_human_approval_is_rejected(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    # Only constructible with the gate's private key; grant() would refuse it.
    spec = make_spec()
    expires = NOW + timedelta(minutes=5)
    approval = Approval(spec.digest(), MODEL, expires, gate._mac(spec.digest(), MODEL, expires))
    assert gate.evaluate(spec, MODEL, approval, now=NOW).reasons == (
        "approval was not granted by a human",
    )


def test_approval_is_bound_to_exact_spec(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    approval = gate.grant(make_spec(), HUMAN, now=NOW)
    other = make_spec(options={"n_samples": 402})
    decision = gate.evaluate(other, MODEL, approval, now=NOW)
    assert decision.reasons == ("approval is bound to a different experiment spec",)


def test_approval_is_single_use(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, now=NOW)
    assert gate.evaluate(spec, MODEL, approval, now=NOW).allowed
    replay = gate.evaluate(spec, MODEL, approval, now=NOW)
    assert replay.decision is Decision.DENY
    assert replay.reasons == ("approval has already been used",)


def test_denied_attempt_does_not_consume_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, now=NOW)
    assert not gate.evaluate(spec, MODEL, approval, now=datetime(2026, 1, 1)).allowed
    assert gate.evaluate(spec, MODEL, approval, now=NOW).allowed


def test_expired_approval_is_denied(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, ttl=timedelta(minutes=1), now=NOW)
    decision = gate.evaluate(spec, MODEL, approval, now=NOW + timedelta(minutes=1))
    assert decision.reasons == ("approval has expired",)


# --- documented gap -----------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN GAP: grant() trusts a self-declared HUMAN principal; human "
    "authentication belongs to the WARDEN migration. This test must start "
    "passing (and the xfail be removed) when that is implemented.",
)
def test_in_process_code_cannot_self_declare_human_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    impostor = Principal(PrincipalKind.HUMAN, "not-actually-a-human")
    with pytest.raises(ApprovalError):
        gate.grant(make_spec(), impostor)
