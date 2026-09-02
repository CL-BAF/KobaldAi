# Legacy migration manifest

This file is the authoritative record of what moves from `CL-BAF/Kobald` into
KobaldAi. Status is based on the late-July legacy baseline previously reporting
1,090 passing tests and 2 skipped; exact source paths and current results must be
verified from a fresh legacy checkout before implementation begins.

## Status vocabulary

- `inventory`: known to exist, exact behaviour/files still being recorded
- `ready`: source, tests, dependencies and target design recorded
- `migrating`: active bounded port or rewrite
- `verified`: target tests pass and deliberate differences are documented
- `deferred`: intentionally scheduled for a later phase
- `rejected`: will not enter the new implementation

## Component manifest

| Legacy component | Target domain | Strategy | Status | Required evidence |
|---|---|---|---|---|
| Configuration | `config` | rewrite typed boundary | inventory | legacy keys, precedence and failure tests |
| Shared models/types | `core` | selective rewrite | inventory | public types and import graph |
| WARDEN | `policy` | port behaviour, clean interface | inventory | decision matrix and approval tests |
| AUDITOR | `audit` | port with storage review | inventory | event schema, integrity and failure tests |
| State sealing | `runtime` | port after cryptographic review | inventory | threat assumptions and tamper tests |
| Persistent task state | `runtime` | rewrite around explicit lifecycle | inventory | recovery and rollback tests |
| Ollama/local/cloud providers | `providers` | rewrite adapters and capabilities | inventory | timeout, consent and privacy tests |
| Knowledge Vault | `knowledge` | selective port | inventory | schema, retrieval and persistence tests |
| Evidence/provenance | `knowledge` | port and consolidate | inventory | citation/claim integrity tests |
| Research sessions | `research` | rewrite against new domains | deferred | verified source and contradiction tests |
| Agent runtime | `agents`, `runtime` | substantial rewrite | deferred | end-to-end prompt/tool lifecycle tests |
| Tool schemas/timeouts | `agents`, `integrations` | port typed contracts | deferred | validation and timeout tests |
| HTTP control plane | `api` | rewrite versioned protocol | deferred | contract and authentication tests |
| Task event streaming | `api` | rewrite bounded streaming | deferred | disconnect/backpressure tests |
| Chat CLI | external client or `api` client | rewrite as protocol client | deferred | client contract tests |
| Supervisor | `supervisor` | major rewrite with smaller authority | deferred | loop and verification tests |
| PySide6 Command Centre | separate client | retain only protocol concepts | deferred | shared protocol compliance |
| Windows packaging | client/build concern | redesign later | deferred | reproducible package test |
| Training scaffold | `training` | use concepts, replace scaffold | deferred | executable pipeline and eval gates |
| Security tool integrations | `integrations` | isolated plugins | deferred | asset scope and policy tests |
| Hardware/sensor integrations | `integrations` | new isolated adapters | deferred | simulator tests before live devices |
| Legacy `jarvis-core` paths/names | none | do not migrate | rejected | guardrail test |

## Known failures that must become regression tests

- context construction failure causing all tasks to fail
- pause/resume concurrency races
- uncertainty after interrupted state-changing actions
- runtime-summary hangs
- uncancellable model probes exhausting a thread pool
- stale or stuck task-event streaming
- GUI requests omitting required conversation identifiers

## Per-component migration record

Every component moving to `ready` must add a record with:

```text
Legacy commit:
Legacy source files:
Legacy tests:
Observed behaviour:
Security/trust boundary:
Target interface:
Deliberate differences:
New tests:
Verification result:
```

## First migration slice

The first implementation slice is `config` plus only the shared `core` types it
requires. WARDEN must follow as its own reviewable change; it must not be bundled
with config merely to make the first change look larger.
