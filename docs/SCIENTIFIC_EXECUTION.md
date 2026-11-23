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
and `completed_verification_failed`. Non-final statuses are `running` and `interrupted`.

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

- **Deny by default:** only allow-listed `(engine, task)` pairs within policy caps run.
- **Model-initiated execution is disabled.** A request from a `PrincipalKind.MODEL`
  principal is denied unless the policy sets `allow_model_requests=True`, which
  nothing in the product does; only the approval-boundary tests do.
- **Approval mechanism (for when model requests are enabled).** An approval is
  bound to the exact spec digest and an expiry. It is **single-use**, and it carries
  an HMAC-SHA256 made with a per-gate random key. Anything that is not a
  gate-issued `Approval` object fails closed, including model-emitted JSON.
- **Trust assumptions — what the approval HMAC does NOT give you:**
  - It defends only against forgery through *data channels*, such as a model
    emitting text or JSON.
  - It does **not** authenticate humans. `grant()` trusts a self-declared
    `PrincipalKind.HUMAN`, and any code in the same Python process can call it or
    read the key. This is pinned by a strict-xfail test that must flip when WARDEN
    provides real authentication.
  - Approvals live in memory only and do not survive a restart.
  - The earlier statement that approvals "cannot be forged" was overstated. It holds
    only under the data-channel assumption above.
- **Models cannot verify:** verification reports come only from supervisor verifiers.
  The report renders the verdict from the record and never upgrades it. Tasks without
  a registered reference are explicitly `NOT VERIFIED`.
- **Total experiment budget:** wall time and output bytes are shared across all
  executions of an experiment (primary, replicate, refined). Spawn, termination and
  reaping all count. If the budget runs out before a verification run, the experiment
  ends `failed` at stage `budget:<role>`; verification is never silently skipped.
  Memory is a per-process limit.
- **Sandbox:** see [SANDBOX.md](SANDBOX.md) for the per-platform audit. In short:
  - **Enforced:** environment scrubbing, process-tree control, a wall-clock limit,
    and a memory cap (a Windows Job Object; `RLIMIT_AS` on POSIX).
  - **Not enforced:** network isolation, filesystem confinement and privilege
    reduction.

The gate is a narrow precursor and **not** the WARDEN migration. WARDEN will wrap or
replace it in its own reviewable change; see `MIGRATION.md` and the migration
records on the `migration/warden` and `migration/auditor` branches. AI-driven execution is **not enabled**.

## Interrupted and failed runs

- `record.json` is written as soon as the run directory exists, with status
  `running`. It is rewritten at every terminal state. A hard kill leaves an honest
  `running` record behind.
- On `KeyboardInterrupt` or any other exception, the record becomes `interrupted`,
  the report is written, and the exception propagates.
- Records and digests are written atomically: a temporary file, then `fsync`, then
  `os.replace`.
- `kobald-science verify-record RUN_DIR` independently re-checks a run:
  - `record.json` against `record.sha256`;
  - every artifact and output table against its recorded hash;
  - non-final statuses (`running`, `interrupted`) are flagged as incomplete.

## Reproducibility record

`record.json` contains the original spec and its digest; the policy decision and
any approval; SI-normalised parameters with original units and dimensions; resolved
options; the seed; engine id, adapter class and version; Python, platform and
package versions; the requester; the total budget and what was used; per-execution
allowances, sandbox limits actually applied, peak memory and diagnostics; and
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
