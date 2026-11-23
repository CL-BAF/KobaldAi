"""Operator CLI for the scientific execution framework.

``kobald-science engines`` lists detected engines and adapters.
``kobald-science run SPEC.json`` runs an experiment as the local human operator.
``kobald-science verify-record RUN_DIR`` re-checks a run's record and artifact hashes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from kobald.integrations.science.registry import ScienceEngineRegistry, default_registry
from kobald.policy.science import (
    Principal,
    PrincipalKind,
    ScientificExecutionGate,
    ScientificExecutionPolicy,
)
from kobald.research.records import verify_record
from kobald.research.spec import ExperimentSpec, SpecError
from kobald.runtime.sandbox import SubprocessSandbox
from kobald.runtime.science import ExperimentRunner
from kobald.supervisor.oscillator import DampedOscillatorVerifier
from kobald.supervisor.rabi import RabiVerifier

__all__ = ["build_runner", "main"]

LOCAL_OPERATOR = Principal(PrincipalKind.HUMAN, "local-operator")


def build_runner(
    runs_root: Path, registry: ScienceEngineRegistry | None = None
) -> ExperimentRunner:
    registry = registry or default_registry()
    policy = ScientificExecutionPolicy(allowed_tasks=frozenset(registry.tasks()))
    return ExperimentRunner(
        registry=registry,
        gate=ScientificExecutionGate(policy),
        backend=SubprocessSandbox(),
        runs_root=runs_root,
        verifiers=[DampedOscillatorVerifier(), RabiVerifier()],
    )


def _engines(out: TextIO, as_json: bool) -> int:
    statuses = default_registry().discover()
    if as_json:
        out.write(json.dumps([s.to_dict() for s in statuses], indent=2) + "\n")
        return 0
    out.write(f"{'engine':<10} {'domain':<12} {'version':<14} {'level':<24} tasks\n")
    for status in statuses:
        out.write(
            f"{status.descriptor.engine_id:<10} {status.descriptor.domain:<12} "
            f"{status.probe.version or '-':<14} {status.level.value:<24} "
            f"{', '.join(status.tasks) or '-'}\n"
        )
    return 0


def _run(out: TextIO, spec_path: Path, runs_root: Path) -> int:
    try:
        spec = ExperimentSpec.from_dict(json.loads(spec_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, SpecError) as error:
        out.write(f"error: cannot load spec: {error}\n")
        return 2
    result = build_runner(runs_root).run(spec, LOCAL_OPERATOR)
    verification = result.record.get("verification", {})
    out.write(f"status: {result.status}\n")
    out.write(f"verification: {verification.get('status', 'not run')}\n")
    for check in verification.get("checks", []):
        mark = "pass" if check["passed"] else "FAIL"
        out.write(
            f"  [{mark}] {check['name']}: {check['measured']} (threshold {check['threshold']})\n"
        )
    out.write(f"record: {result.run_dir / 'record.json'} (sha256 {result.record_digest})\n")
    out.write(f"report: {result.run_dir / 'report.md'}\n")
    return 0 if result.status == "completed" and verification.get("status") == "passed" else 1


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="kobald-science")
    sub = parser.add_subparsers(dest="command", required=True)
    engines = sub.add_parser("engines", help="list scientific engines and adapters")
    engines.add_argument("--json", action="store_true")
    run = sub.add_parser("run", help="run an experiment spec as the local operator")
    run.add_argument("spec", type=Path)
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    check = sub.add_parser("verify-record", help="re-check a run directory's hashes")
    check.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "engines":
        return _engines(out, args.json)
    if args.command == "verify-record":
        return _verify(out, args.run_dir)
    return _run(out, args.spec, args.runs_dir)


def _verify(out: TextIO, run_dir: Path) -> int:
    problems = verify_record(run_dir)
    for problem in problems:
        out.write(f"problem: {problem}\n")
    out.write("record verified\n" if not problems else f"{len(problems)} problem(s)\n")
    return 0 if not problems else 1
