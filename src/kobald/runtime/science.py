"""Experiment orchestration: validate -> authorise -> execute -> verify -> record -> report.

Every path, including invalid input, policy denial and engine failure, ends
with a persisted ``record.json`` and ``report.md`` so failures are never lost.
"""

from __future__ import annotations

import csv
import secrets
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kobald import __version__
from kobald.integrations.science.registry import ScienceEngineRegistry, UnknownEngineTaskError
from kobald.policy.science import Approval, Decision, Principal, ScientificExecutionGate
from kobald.research.figures import plot_against_reference
from kobald.research.hashing import file_sha256, float_array_sha256
from kobald.research.records import RECORD_SCHEMA_VERSION, capture_environment, write_record
from kobald.research.report import render_report
from kobald.research.spec import ExperimentSpec, OptionValue
from kobald.research.units import UnitValidationError, normalize_parameters, validate_options
from kobald.runtime.sandbox import ExecutionBackend, SandboxOutcome, SandboxStatus
from kobald.supervisor.verification import (
    ReferenceVerifier,
    RunArrays,
    VerificationReport,
    not_verifiable,
)

__all__ = ["ExperimentRunner", "OutputIntegrityError", "RunResult", "load_table", "redact_paths"]

_ENVIRONMENT_PACKAGES = ("kobald-ai", "numpy", "scipy", "pint", "matplotlib")


class OutputIntegrityError(RuntimeError):
    """Raised when engine output does not match the hashes it declared."""


@dataclass(frozen=True, slots=True)
class RunResult:
    status: str
    run_dir: Path
    record: dict[str, Any]
    record_digest: str


def load_table(workdir: Path, result: Mapping[str, Any]) -> tuple[RunArrays, dict[str, str]]:
    """Load the CSV written by the worker and check it against declared hashes."""
    table = (workdir / str(result["table"])).resolve()
    if workdir.resolve() not in table.parents:
        raise OutputIntegrityError("table path escapes the working directory")
    declared = result["columns"]
    with table.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = [f"{c['name']} [{c['unit']}]" for c in declared]
    if not rows or rows[0] != header:
        raise OutputIntegrityError("table header does not match declared columns")
    columns = list(zip(*(map(float, row) for row in rows[1:]), strict=True)) or [
        () for _ in declared
    ]
    arrays: dict[str, tuple[float, ...]] = {}
    for column, values in zip(declared, columns, strict=True):
        if float_array_sha256(values) != column["sha256"]:
            raise OutputIntegrityError(f"column {column['name']} does not match its hash")
        arrays[column["name"]] = tuple(values)
    return arrays, {c["name"]: c["unit"] for c in declared}


def redact_paths(value: Any, replacements: Sequence[tuple[str, str]]) -> Any:
    """Recursively replace local path prefixes in every string of a record."""
    if isinstance(value, str):
        for needle, placeholder in replacements:
            value = value.replace(needle, placeholder)
        return value
    if isinstance(value, dict):
        return {key: redact_paths(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_paths(item, replacements) for item in value]
    return value


def _path_replacements(run_dir: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for path, placeholder in (
        (run_dir.resolve(), "<run_dir>"),
        (Path(sys.prefix), "<python_prefix>"),
        (Path(sys.base_prefix), "<python_base_prefix>"),
        (Path.home(), "<home>"),
    ):
        for form in {str(path), path.as_posix()}:
            pairs.append((form, placeholder))
    # Longest first so the most specific prefix wins.
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _utc_stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


class ExperimentRunner:
    def __init__(
        self,
        registry: ScienceEngineRegistry,
        gate: ScientificExecutionGate,
        backend: ExecutionBackend,
        runs_root: Path,
        verifiers: Iterable[ReferenceVerifier] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._registry = registry
        self._gate = gate
        self._backend = backend
        self._runs_root = runs_root
        self._verifiers = {v.key: v for v in verifiers}
        self._clock = clock

    def run(
        self, spec: ExperimentSpec, requester: Principal, approval: Approval | None = None
    ) -> RunResult:
        now = self._clock()
        digest = spec.digest()
        record_id = f"{spec.experiment_id}-{_utc_stamp(now)}-{digest[:8]}-{secrets.token_hex(2)}"
        run_dir = self._runs_root / record_id
        run_dir.mkdir(parents=True, exist_ok=False)
        decision = self._gate.evaluate(spec, requester, approval, now)
        record: dict[str, Any] = {
            "record_schema_version": RECORD_SCHEMA_VERSION,
            "record_id": record_id,
            "created_at": now.isoformat(),
            "status": "pending",
            "spec": spec.to_dict(),
            "spec_digest": digest,
            "policy": decision.to_dict(),
            "approval": approval.to_dict() if approval is not None else None,
            "kobald_version": __version__,
            "environment": capture_environment(_ENVIRONMENT_PACKAGES),
            "input_datasets": [],
            "executions": [],
            "errors": [],
        }

        try:
            adapter, definition = self._registry.resolve(spec.engine, spec.task)
            parameters = normalize_parameters(spec.parameters, definition.parameters)
            options = validate_options(spec.options, definition.options)
        except (UnknownEngineTaskError, UnitValidationError) as error:
            record["errors"].append({"stage": "validation", "message": str(error)})
            return self._finish(run_dir, record, "invalid", None)

        record["parameters"] = {name: p.to_dict() for name, p in parameters.items()}
        record["options"] = options
        if decision.decision is not Decision.ALLOW:
            status = (
                "awaiting_approval" if decision.decision is Decision.REQUIRE_APPROVAL else "denied"
            )
            return self._finish(run_dir, record, status, None)

        si = {name: p.si_value for name, p in parameters.items()}
        primary = self._execute(spec, si, options, "primary", run_dir, record)
        if primary is None:
            return self._finish(run_dir, record, "failed", None)
        arrays, units, engine_version = primary
        record["engine"] = {
            "id": spec.engine,
            "adapter": f"{type(adapter).__module__}.{type(adapter).__qualname__}",
            "version": engine_version,
        }

        verifier = self._verifiers.get((spec.engine, spec.task))
        if verifier is None:
            report = not_verifiable("no independent reference is registered for this task")
        else:
            replicate = self._execute(spec, si, options, "replicate", run_dir, record)
            refined_options = verifier.refinement_options(options)
            refined = self._execute(spec, si, refined_options, "refined", run_dir, record)
            if replicate is None or refined is None:
                return self._finish(run_dir, record, "failed", None)
            report = verifier.verify(si, spec.tolerance, arrays, units, replicate[0], refined[0])
        record["verification"] = report.to_dict()
        figure = self._figure(run_dir, report, arrays, units, spec)
        status = "completed" if report.status.value != "failed" else "completed_verification_failed"
        return self._finish(run_dir, record, status, figure)

    def _execute(
        self,
        spec: ExperimentSpec,
        si: dict[str, float],
        options: Mapping[str, OptionValue],
        role: str,
        run_dir: Path,
        record: dict[str, Any],
    ) -> tuple[RunArrays, dict[str, str], str] | None:
        job = {
            "engine": spec.engine,
            "task": spec.task,
            "parameters": si,
            "options": dict(options),
            "seed": spec.seed,
        }
        workdir = run_dir / f"exec-{role}"
        outcome: SandboxOutcome = self._backend.execute(job, workdir, spec.budget)
        entry: dict[str, Any] = {
            "role": role,
            "options": dict(options),
            "workdir": workdir.name,
            "sandbox": outcome.to_dict(),
        }
        record["executions"].append(entry)
        if outcome.status is not SandboxStatus.OK or outcome.result is None:
            detail = outcome.result.get("message", "") if outcome.result is not None else ""
            record["errors"].append(
                {
                    "stage": f"execution:{role}",
                    "message": f"{outcome.status.value} {detail}".strip(),
                    "stderr_tail": outcome.stderr_tail[-1000:],
                }
            )
            return None
        try:
            arrays, units = load_table(workdir, outcome.result)
        except (OutputIntegrityError, OSError, ValueError, KeyError) as error:
            record["errors"].append({"stage": f"output:{role}", "message": str(error)})
            return None
        entry["outputs"] = {
            "table": f"{workdir.name}/{outcome.result['table']}",
            "table_sha256": file_sha256(workdir / str(outcome.result["table"])),
            "columns": outcome.result["columns"],
            "diagnostics": outcome.result["diagnostics"],
            "warnings": outcome.result["warnings"],
        }
        return arrays, units, str(outcome.result["engine_version"])

    def _figure(
        self,
        run_dir: Path,
        report: VerificationReport,
        arrays: RunArrays,
        units: Mapping[str, str],
        spec: ExperimentSpec,
    ) -> str | None:
        reference = report.reference_series
        if not reference:
            return None
        names = [n for n in reference if n != "time" and n in arrays]
        plot_against_reference(
            run_dir / "figure.png",
            arrays["time"],
            {n: (arrays[n], reference[n], units[n]) for n in names},
            f"{spec.engine}/{spec.task}: engine output vs independent reference",
        )
        return "figure.png"

    def _finish(
        self, run_dir: Path, record: dict[str, Any], status: str, figure: str | None
    ) -> RunResult:
        record["status"] = status
        # Tracebacks and stderr can contain usernames and install paths; never persist them.
        record = redact_paths(record, _path_replacements(run_dir))
        artifacts: dict[str, str] = {}
        if figure is not None:
            artifacts[figure] = file_sha256(run_dir / figure)
        report_text = render_report(record, figure)
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")
        artifacts["report.md"] = file_sha256(run_dir / "report.md")
        record["artifacts"] = artifacts
        digest = write_record(run_dir, record)
        return RunResult(status, run_dir, record, digest)
