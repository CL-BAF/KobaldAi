# Architecture

## Purpose

KobaldAi is the canonical implementation of Kobald. It coordinates models, tools,
knowledge and managed systems while keeping authority, execution, oversight and
audit responsibilities separate.

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
| `research` | research jobs and evidence evaluation | training models directly |
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
