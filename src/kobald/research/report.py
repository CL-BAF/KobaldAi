"""Readable Markdown report rendered solely from an execution record.

The report never contains claims that are not in the record. Verification
language comes from the supervisor verdict; nothing here can upgrade it.
"""

from __future__ import annotations

from typing import Any

__all__ = ["render_report"]

_VERDICT_TEXT = {
    "passed": "PASSED — every independent check met its threshold.",
    "failed": "FAILED — at least one independent check did not meet its threshold.",
    "not_verifiable": "NOT VERIFIED — no independent reference is available for this task.",
}


def _fmt(value: object) -> str:
    """Format a value for a Markdown table cell."""
    text = f"{value:.6g}" if isinstance(value, float) else str(value)
    return text.replace("|", "\\|")


def render_report(record: dict[str, Any], figure: str | None) -> str:
    spec = record["spec"]
    lines = [
        f"# Kobald experiment report: `{spec['experiment_id']}`",
        "",
        f"- **Record:** `{record['record_id']}` (schema v{record['record_schema_version']})",
        f"- **Status:** {record['status']}",
        f"- **Spec digest:** `{record['spec_digest']}`",
        f"- **Created (UTC):** {record['created_at']}",
        "",
        "## Research question",
        "",
        spec["question"],
        "",
    ]
    policy = record.get("policy")
    if policy is not None:
        lines += [
            "## Policy decision",
            "",
            f"{policy['decision']} — " + "; ".join(policy["reasons"]),
            "",
        ]

    if record.get("parameters"):
        lines += [
            "## Method",
            "",
            f"Engine `{spec['engine']}` task `{spec['task']}`"
            + (
                f" (engine version {record['engine']['version']})." if record.get("engine") else "."
            ),
            "",
            "| Parameter | As submitted | SI value | Dimension |",
            "|---|---|---|---|",
        ]
        for name, p in record["parameters"].items():
            lines.append(
                f"| {name} | {_fmt(p['original']['value'])} {p['original']['unit']} "
                f"| {_fmt(p['si_value'])} {p['si_unit']} | `{p['dimension']}` |"
            )
        lines += [
            "",
            "Options: " + ", ".join(f"`{k}={v}`" for k, v in record["options"].items()),
            "",
        ]

    for error in record.get("errors", []):
        lines += [f"> **Error ({error['stage']}):** {error['message']}", ""]

    verification = record.get("verification")
    if verification is not None:
        lines += [
            "## Independent verification",
            "",
            f"**Verdict: {_VERDICT_TEXT[verification['status']]}**",
            "",
            f"Verifier: `{verification['verifier']}`. Reference: {verification['reference']}.",
            "",
        ]
        if verification["checks"]:
            lines += ["| Check | Result | Measured | Threshold | Notes |", "|---|---|---|---|---|"]
            for check in verification["checks"]:
                result = "pass" if check["passed"] else "**FAIL**"
                cells = [check["name"], result, check["measured"], check["threshold"]]
                cells.append(check["detail"])
                lines.append("| " + " | ".join(_fmt(cell) for cell in cells) + " |")
            lines.append("")

    if figure is not None:
        lines += ["## Figure", "", f"![Engine output against reference]({figure})", ""]

    if record.get("executions"):
        lines += [
            "## Executions",
            "",
            "| Role | Status | Duration (s) | Key options |",
            "|---|---|---|---|",
        ]
        for execution in record["executions"]:
            opts = ", ".join(
                f"{k}={v}" for k, v in execution["options"].items() if k in ("rtol", "atol")
            )
            lines.append(
                f"| {execution['role']} | {execution['sandbox']['status']} "
                f"| {execution['sandbox']['duration_s']:.3f} | {opts} |"
            )
        lines.append("")
        limits = record["executions"][0]["sandbox"]["limits"]
        budget = record.get("budget", {})
        lines += [
            "## Reproducibility and limitations",
            "",
            f"- Python {record['environment']['python']} on {record['environment']['platform']}.",
            "- Package versions: "
            + ", ".join(f"{k} {v}" for k, v in record["environment"]["packages"].items()),
            f"- Seed: {spec['seed']} (recorded; deterministic engines do not consume it).",
            f"- Experiment budget ({budget.get('scope', 'unknown')}): "
            f"{budget.get('wall_time_s')} s wall time across all executions, "
            f"{_fmt(budget.get('wall_time_used_s', 0.0))} s used.",
            f"- Sandbox `{limits['backend']}` / `{limits['controller']}`: "
            f"process tree controlled: {limits['process_tree_controlled']}; "
            f"memory limit: {limits['memory_limit_kind'] or 'not enforced'}; "
            f"network isolated: {limits['network_isolated']}; "
            f"filesystem confined: {limits['filesystem_confined']}; "
            f"privileges reduced: {limits['privileges_reduced']}.",
            "- Output column hashes are SHA-256 of little-endian float64 values (see record.json).",
            "",
        ]

    lines += [
        "---",
        "Generated by Kobald from `record.json`. Verification verdicts are produced by the "
        "supervisor verifier, not by the engine or any model.",
        "",
    ]
    return "\n".join(lines)
