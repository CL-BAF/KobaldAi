# Scientific execution framework (milestone 1)

This document describes what is implemented on `feature/scientific-engine-foundation`.
It is the first, intentionally small slice of roadmap Phase 5 ("reproducible
scientific job specification" and "sandboxed simulation runner"). It does **not**
migrate WARDEN, AUDITOR, or the agent runtime.

## Flow

```text
ExperimentSpec (JSON, untrusted)          kobald.research.spec
  -> resolve engine/task                  kobald.integrations.science.registry
  -> validate units/ranges/options (Pint) kobald.research.units
  -> policy gate (deny-by-default)        kobald.policy.science
  -> sandboxed execution x3               kobald.runtime.sandbox + science_worker
       primary / identical replicate / tighter-tolerance refinement
  -> output integrity (hash re-check)     kobald.runtime.science.load_table
  -> independent verification             kobald.supervisor.oscillator
  -> record.json + record.sha256          kobald.research.records
  -> figure.png + report.md               kobald.research.figures / report
```

Every path ends with a persisted record and report, including invalid input, denial,
awaiting approval, engine failure, tampered output and failed verification. The
terminal statuses are `invalid`, `denied`, `awaiting_approval`, `failed`, `completed`
and `completed_verification_failed`.

## Module responsibilities

| Module | Responsibility | Must not |
|---|---|---|
| `research.spec` | Typed, strictly parsed, SHA-256-digested experiment spec | import engines |
| `research.units` | Pint dimensional checks and SI normalisation, option typing | execute anything |
| `integrations.science.catalog` | 18 engine descriptors; detection without importing engines | claim correctness |
| `integrations.science.registry` | `(engine, task)` → adapter resolution; integration levels | authorise |
| `integrations.science.adapters.scipy_ode` | the first adapter (SciPy `solve_ivp`) | contain the reference solution |
| `policy.science` | allow-list, budget caps, human-only approvals bound to spec digest | execute |
| `runtime.sandbox` | child interpreter, timeout, scrubbed env, output caps | judge results |
| `runtime.science` | orchestration, failure capture, record/report writing | grant authority |
| `supervisor.oscillator` | closed-form reference and checks | import any adapter |
| `providers.base` | model-agnostic `ModelProvider` protocol | reach policy/runtime/supervisor |

`tests/test_science_verification.py::test_domain_boundaries` enforces the import rules
with an AST scan.

## Security properties (and their limits)

- **Deny by default:** only allow-listed `(engine, task)` pairs run. Budgets above
  policy caps are denied.
- **Models cannot authorise:** requests from a `PrincipalKind.MODEL` principal return
  `awaiting_approval` unless they carry an approval. `grant()` refuses non-human
  approvers. An approval is bound to the spec digest and an expiry, and is
  HMAC-authenticated with a per-gate random key, so a forged or replayed approval
  is rejected.
- **Models cannot verify:** verification reports come only from supervisor verifiers.
  The report renders the verdict from the record and never upgrades it. Tasks without
  a registered reference are explicitly `NOT VERIFIED`.
- **Sandbox — enforced:** separate `python -I` process, dedicated working directory,
  scrubbed environment (API keys and user variables are not inherited), wall-clock
  kill, output-size cap, single-threaded BLAS/OpenMP.
- **Budget scope:** the spec's resource budget applies **per execution**. A verified
  task runs three executions (primary, replicate, refined), so it can use up to 3× the
  stated wall time.
- **Sandbox — enforced only on POSIX:** memory (`RLIMIT_AS`) and CPU-time rlimits.
- **Sandbox — not enforced:** network isolation, filesystem confinement, and memory
  limits on Windows. Every record states these flags (`memory_limit_enforced`,
  `network_isolated`, `filesystem_confined`). A Windows Job Object backend or a
  WSL2/container backend is the next hardening step.

The gate is a narrow precursor and **not** the WARDEN migration. WARDEN will wrap or
replace it in its own reviewable change (see `MIGRATION.md`). AI-driven execution
(a model submitting specs through a tool loop) is **not enabled**. Only the provider
protocol and the approval boundary exist.

## Reproducibility record

`record.json` contains the original spec and its digest; the policy decision and
any approval; SI-normalised parameters with original units and dimensions; resolved
options; the seed; engine id, adapter class and version; Python, platform and
package versions; sandbox limits actually applied; per-execution diagnostics; and
SHA-256 hashes of output columns (packed little-endian float64), of the CSV table,
the figure and the report. `input_datasets` is present but empty, because the demo
has no input data. Hostnames are not collected. Local path prefixes (the run
directory, the Python installation and the home directory) are redacted from every
string in the record, including failure tracebacks. Raw `exec-*/stderr.log` files in
the run directory are kept unredacted for local debugging.

Run directories go to `runs/`, which is gitignored.

## First demonstration

```powershell
kobald-science run examples/damped_oscillator/spec.json
```

See `examples/damped_oscillator/README.md` for the research question and the
actual results.

## Adding an engine adapter

1. Implement `EngineAdapter` in `integrations/science/adapters/<engine>.py`, and import
   the engine lazily inside `run()`.
2. Declare each task's `ParameterRule`s (SI unit = dimension), `OptionRule`s and
   output units.
3. Register it in `default_registry()`. It runs only once a policy allow-lists the task.
4. Add an independent `ReferenceVerifier` in `supervisor/` that does not import the
   adapter. Without one, results are recorded as `not_verifiable`.
5. Add tests covering validation, failure paths and a real (unmocked) run.
