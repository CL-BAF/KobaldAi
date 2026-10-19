# Roadmap

## Mission

Develop Kobald as a **scientific AI harness**, not a general-purpose daily assistant. Scientific simulation, chemical analysis, measurable research workflows and controlled laboratory-data integrations are the destination. Existing models can power Kobald independently of any future Domovoi research outcome.

This is a staged, potentially multi-year research-engineering direction, **not** a claim that scientific integrations already exist. Phase labels indicate technical dependencies, not promises about timing.

The order is deliberate. A later phase must not weaken guarantees established by
an earlier one.

## Phase 0: Foundation — in progress

- [x] Establish `KobaldAi` as the canonical source repository
- [x] Define package and subsystem boundaries
- [x] Add tests, linting, typing and continuous integration
- [x] Create the migration manifest and technical documentation
- [ ] Record a complete legacy file/test inventory for the first migration slice

Exit condition: the scaffold passes locally and in CI, and the first migration
slice has named source files, behaviours, risks and tests.

## Phase 1: Trusted foundation

- [ ] Configuration and shared domain types
- [ ] WARDEN policy and approval model
- [ ] AUDITOR event model and append-only storage
- [ ] Authenticated persistent state and rollback detection
- [ ] Model-provider abstraction
- [ ] Knowledge Vault and evidence/provenance model

Exit condition: every migrated subsystem has explicit interfaces, parity evidence
and tests for rejection/failure paths.

## Phase 2: Agent runtime

- [ ] Task lifecycle and secure persistent state
- [ ] Planner and context construction
- [ ] Typed tool proposals and constrained execution
- [ ] Pause, resume, cancel and interrupted-action reconciliation
- [ ] Regression suite for known legacy runtime failures

## Phase 3: Control plane and interfaces

- [ ] Versioned API contract
- [ ] Task management and event streaming
- [ ] Approval and reconciliation endpoints
- [ ] CLI client
- [ ] Command Centre client migration
- [ ] Pocket Kobald client migration

## Phase 4: Supervisor v2

- [ ] Progress and loop detection
- [ ] Source, claim and tool-output verification
- [ ] Suspicious-behaviour reporting
- [ ] Clear separation from WARDEN authority

## Phase 5: Scientific research and evaluation system

- [ ] Reproducible scientific job specification: inputs, units, methods, versions, seeds and budgets
- [ ] Sandboxed simulation runner and independently testable result capture
- [ ] Read-only chemistry/data-analysis adapter with a small openly documented test dataset
- [ ] Real research-task execution backend
- [ ] Raw and scored trajectory stores
- [ ] Supervisor verification pipeline
- [ ] Train, validation and test dataset splits
- [ ] Evaluation harness and acceptance gates
- [ ] First LoRA/QLoRA/SFT Kobald candidate
- [ ] Model registry, promotion and rollback

## Phase 6: Deployment and integrations

- [ ] Run legacy Kobald and KobaldAi side by side with isolated state
- [ ] Compare harmless task suites and operational behaviour
- [ ] Cut clients over only after acceptance gates pass
- [ ] Freeze the legacy implementation as read-only reference
- [ ] Introduce managed hardware, sensor and security-tool integrations
- [ ] Introduce scientific instrument connectors only after read-only simulation, policy testing, approval and device-specific safety reviews
- [ ] Update `Kobald_Showcase` from proven KobaldAi results

## Scientific expansion after foundation phases

These milestones may run across multiple releases after the core runtime and security boundaries exist:

1. **First reproducible dry-lab demonstration:** use a documented physics or numerical simulation and independently check outputs against known results.
2. **Computational chemistry demonstration:** analyse existing chemical data without controlling a physical instrument.
3. **Instrument interoperability:** define typed connectors and replayable synthetic instrument messages, then trial read-only hardware measurements with appropriate supervision.
4. **Research workflows:** compose analyses, maintain data and method lineage, quantify uncertainty and enable human comparison of experimental runs.
5. **Research-grade evaluation:** benchmark correctness, repeatability, cost, failure handling, user oversight and security—not just LLM answer quality.

Physical experiment initiation, hazardous actuation and autonomous laboratory control are not baseline milestones and require separate safety, governance and specialist review.

## Parallel evidence work

Record the migration decision, test captures, approval-flow capture, hardware
inventory, external technical feedback and evaluation in `AIF-PROJECT` as each is
produced. Do not manufacture evidence ahead of the actual work.
