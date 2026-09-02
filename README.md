# KobaldAi

KobaldAi is the canonical source repository for Kobald: a locally operated AI and
smart-systems platform built around evidence, explicit authority, auditable tool
use, and human control over important actions.

This repository is a clean successor to the legacy
[`CL-BAF/Kobald`](https://github.com/CL-BAF/Kobald) prototype. Legacy components
will be audited and migrated one subsystem at a time with their tests. The old
repository remains a reference implementation; it is not copied wholesale.

## Current status

**v0.1 foundation bootstrap**

- package and domain boundaries established
- architecture, roadmap, security, training and migration decisions documented
- automated quality checks and tests configured
- no legacy runtime implementation migrated yet

See [the migration manifest](docs/MIGRATION.md) for the authoritative component
status and [the roadmap](docs/ROADMAP.md) for the order of work.

## Repository roles

| Repository | Purpose |
|---|---|
| `KobaldAi` | Current source code and technical documentation |
| `Kobald` | Frozen-in-place legacy implementation and migration source |
| `Kobald_Showcase` | Public-facing project showcase |
| `AIF-PROJECT` | School evidence, reflection and evaluation |

## Development setup

KobaldAi currently requires Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

Run all local quality checks with:

```powershell
python -m ruff check .
python -m mypy src
python -m pytest
```

## Structure

```text
src/kobald/
├── core/          Shared types and application primitives
├── config/        Configuration loading and validation
├── policy/        Authority and policy decisions (WARDEN)
├── audit/         Append-only security and action records (AUDITOR)
├── knowledge/     Knowledge Vault, evidence and provenance
├── providers/     Local and cloud model provider adapters
├── agents/        Agent planning and tool-use behaviour
├── runtime/       Task lifecycle and execution orchestration
├── supervisor/    Oversight, verification and loop detection
├── research/      Research sessions and source/claim evaluation
├── training/      Verified trajectory datasets and model training
├── api/           Shared control-plane protocol and server
└── integrations/  External tools, devices and services
```

The operator interfaces (Command Centre, CLI, Pocket Kobald and any future web
client) must use the shared control-plane protocol rather than reimplementing
Kobald behaviour.

## Non-negotiable migration rules

1. Migrate one bounded subsystem at a time.
2. Understand and document the legacy behaviour before porting it.
3. Bring or rewrite tests with every migrated subsystem.
4. Keep policy, audit and execution responsibilities separate.
5. Never silently weaken approval, provenance or state-integrity guarantees.
6. Add regression tests for every known legacy failure being preserved against.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Migration manifest](docs/MIGRATION.md)
- [Security model](docs/SECURITY.md)
- [Training design](docs/TRAINING.md)
- [Contributing](CONTRIBUTING.md)
