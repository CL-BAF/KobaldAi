# Roadmap

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

## Phase 5: Research and training system

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
- [ ] Update `Kobald_Showcase` from proven KobaldAi results

## Parallel evidence work

Record the migration decision, test captures, approval-flow capture, hardware
inventory, external technical feedback and evaluation in `AIF-PROJECT` as each is
produced. Do not manufacture evidence ahead of the actual work.
