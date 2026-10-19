# Architecture

## Purpose

KobaldAi is the canonical implementation of **Kobald, a proposed scientific AI harness**. It aims to coordinate interchangeable models with trusted scientific software, reproducible computations, research datasets, analytical instruments and human researchers, while keeping authority, execution, oversight and audit responsibilities separate.

It is not intended to be optimised around daily personal-assistant tasks. The scientific integrations described below are architectural targets and do not imply they are implemented.

## Core execution flow

```text
Objective
  -> runtime creates task
  -> agent plans next step
  -> knowledge supplies evidence and context
  -> agent proposes tool action
  -> policy evaluates authority and risk
  -> WARDEN allows, rejects or requests approval
  -> integration executes an allowed action
  -> runtime records the observation
  -> AUDITOR records the event
  -> supervisor independently evaluates progress and output
  -> agent continues or task terminates
```

## Scientific workflow contract (planned)

A future scientific tool call should carry a structured manifest with the experiment or analysis identifier, tool version, input dataset identity and checksum, parameter values and units, numerical precision/tolerances where relevant, random seeds, environment, time/resource budgets, expected output schema and required approval scope.

The corresponding observation should retain output artifacts and hashes, warnings/errors, tool version, provenance, execution context and known limitations. Models may interpret results, but cannot overwrite underlying measurements or approve their own conclusions.

Initial tool integrations should be sandboxed simulations and offline analysis. Instrument connectors begin with read-only or synthetic data. A connector must not execute state-changing laboratory operations without external safeguards, explicit human authority and device-appropriate safety controls.

## Responsibilities

| Domain | Owns | Must not own |
|---|---|---|
| `core` | shared immutable types and primitives | network, storage or UI logic |
| `config` | typed configuration and validation | secrets themselves |
| `policy` | authority, risk and approval decisions | executing tools |
| `audit` | durable security/action records | deciding whether actions are allowed |
| `knowledge` | sources, claims, provenance and retrieval | model/provider transport |
| `providers` | model capabilities and inference adapters | policy decisions |
| `agents` | planning and proposed actions | bypassing policy or directly calling integrations |
| `runtime` | task lifecycle, state and orchestration | UI-specific behaviour |
| `supervisor` | progress and output verification | final policy authority |
| `research` | research jobs, reproducibility metadata and scientific evidence evaluation | training models directly |
| scientific adapters (planned within `integrations`) | typed simulators, analysis programs and constrained instrument access | interpreting results as authoritative or bypassing safety controls |
| `training` | datasets, evaluation, fine-tuning and registry | live runtime authority |
| `api` | shared control-plane contract and transport | duplicating core behaviour |
| `integrations` | constrained external operations | independently granting authority |

## Dependency direction

The `core` domain is the lowest layer. Infrastructure-facing packages may depend
on domain interfaces, but domain packages must not import API, GUI or concrete
integration implementations. Circular dependencies are defects, not conveniences.

## Operator interfaces

Command Centre, CLI, Pocket Kobald and future interfaces are clients of one
versioned control-plane contract. They do not contain separate agent runtimes or
policy engines.

## Asset-aware authority

Kobald will use a trusted asset registry to identify managed machines, ownership,
environment and permitted capability profiles. Familiarity with an IP address is
not itself authority. Policy decisions must be based on explicit registered scope
and auditable permissions.

## Persistence

Runtime state, audit records, credentials, datasets and model artefacts are kept
outside the source tree and are never committed. Persisted task state must support
authentication, rollback detection and reconciliation of interrupted actions.
