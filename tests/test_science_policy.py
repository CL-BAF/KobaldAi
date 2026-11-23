"""Scientific execution gate: deny-by-default, budgets and human-only approval."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

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


@pytest.fixture
def gate() -> ScientificExecutionGate:
    return ScientificExecutionGate(
        ScientificExecutionPolicy(
            allowed_tasks=allow_tasks([("scipy", "damped_harmonic_oscillator")]),
            max_wall_time_s=100.0,
            max_memory_mb=2048,
            max_output_bytes=10_000_000,
        )
    )


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


def test_model_request_requires_human_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    assert gate.evaluate(spec, MODEL).decision is Decision.REQUIRE_APPROVAL
    approval = gate.grant(spec, HUMAN, now=NOW)
    decision = gate.evaluate(spec, MODEL, approval, now=NOW + timedelta(minutes=1))
    assert decision.allowed
    assert approval.to_dict()["approver"]["kind"] == "human"


def test_model_cannot_grant_approval(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    with pytest.raises(ApprovalError, match="only a human"):
        gate.grant(make_spec(), MODEL)


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(hours=2)])
def test_approval_lifetime_is_bounded(
    gate: ScientificExecutionGate, make_spec: SpecFactory, ttl: timedelta
) -> None:
    with pytest.raises(ApprovalError, match="lifetime"):
        gate.grant(make_spec(), HUMAN, ttl=ttl)


def test_forged_approval_is_denied(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    spec = make_spec()
    forged = Approval(spec.digest(), HUMAN, NOW + timedelta(minutes=5), mac="0" * 64)
    decision = gate.evaluate(spec, MODEL, forged, now=NOW)
    assert decision.decision is Decision.DENY
    assert decision.reasons == ("approval is not authentic",)


def test_approval_from_another_gate_is_not_authentic(make_spec: SpecFactory) -> None:
    policy = ScientificExecutionPolicy(
        allowed_tasks=allow_tasks([("scipy", "damped_harmonic_oscillator")])
    )
    spec = make_spec()
    approval = ScientificExecutionGate(policy).grant(spec, HUMAN, now=NOW)
    decision = ScientificExecutionGate(policy).evaluate(spec, MODEL, approval, now=NOW)
    assert decision.reasons == ("approval is not authentic",)


def test_tampered_approver_kind_is_rejected(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, now=NOW)
    tampered = dataclasses.replace(approval, approver=MODEL)
    assert gate.evaluate(spec, MODEL, tampered, now=NOW).reasons == ("approval is not authentic",)
    # Even a correctly MAC'd non-human approval (only constructible with the gate's key) fails.
    expires = NOW + timedelta(minutes=5)
    model_mac = gate._mac(spec.digest(), MODEL, expires)
    model_approval = Approval(spec.digest(), MODEL, expires, model_mac)
    assert gate.evaluate(spec, MODEL, model_approval, now=NOW).reasons == (
        "approval was not granted by a human",
    )


def test_approval_is_bound_to_exact_spec(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    approval = gate.grant(make_spec(), HUMAN, now=NOW)
    other = make_spec(options={"n_samples": 402})
    decision = gate.evaluate(other, MODEL, approval, now=NOW)
    assert decision.reasons == ("approval is bound to a different experiment spec",)


def test_expired_approval_is_denied(gate: ScientificExecutionGate, make_spec: SpecFactory) -> None:
    spec = make_spec()
    approval = gate.grant(spec, HUMAN, ttl=timedelta(minutes=1), now=NOW)
    decision = gate.evaluate(spec, MODEL, approval, now=NOW + timedelta(minutes=1))
    assert decision.reasons == ("approval has expired",)


def test_policy_denial_takes_precedence_over_approval(
    gate: ScientificExecutionGate, make_spec: SpecFactory
) -> None:
    spec = make_spec(budget={"wall_time_s": 500})
    approval = gate.grant(spec, HUMAN, now=NOW)
    assert gate.evaluate(spec, MODEL, approval, now=NOW).decision is Decision.DENY
