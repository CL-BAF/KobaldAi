# KobaldAi

**Kobald is an evidence-first AI harness for scientific investigation.** Its long-term purpose is to help researchers use interchangeable AI models alongside scientific software, simulations, datasets, analytical tools and—where safely authorised—laboratory instrumentation.

Kobald is **not primarily an everyday personal assistant**. The intended system is a research orchestration layer: models can propose analyses, invoke constrained scientific tools, preserve inputs and outputs, compare results with evidence, and present reproducible findings for human examination. Scientific conclusions are not validated merely because an AI or tool produced them.

Scientific domains under consideration include physics simulation, chemistry and chemical data analysis, computational biology, mathematics, engineering and experimental data processing. Planned instrument connectors are **not** a claim of existing laboratory control.

This is the canonical successor to the legacy [`CL-BAF/Kobald`](https://github.com/CL-BAF/Kobald) prototype. Existing security, evidence, agent and model-provider work is foundation material to evaluate and migrate—not evidence that the proposed scientific integrations already exist.

**Separate project:** [Domovoi](https://github.com/CL-BAF/Domovoi-Kobald_showcase) is a proposed, long-term investigation into more memory- and compute-efficient AI architectures. Domovoi research has not yet produced a validated model or benchmark result. Kobald must remain useful with existing models whether or not Domovoi succeeds.

## Current status

**v0.1 foundation bootstrap; scientific focus is a planned direction, not implemented functionality.**

- Package and domain boundaries, architecture, roadmap, security and migration decisions are documented.
- Automated quality checks and tests are configured.
- No legacy runtime implementation has been migrated into this canonical repository yet.
- Physics-engine adapters, chemical analysis workflows, scientific instrument connectors and end-to-end scientific experiments are **not implemented** here.
- The older Kobald prototype contains evidence/provenance and controlled research workflow foundations; these need deliberate migration and revalidation.

See the [migration manifest](docs/MIGRATION.md) for component status and the [roadmap](docs/ROADMAP.md) for delivery stages.

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

## Scientific research workflow (target design)

```text
Research question / hypothesis
    -> select datasets and approved scientific tools
    -> capture inputs, units, assumptions and versions
    -> run simulations or analysis in isolated, bounded environments
    -> record outputs, parameters, errors and provenance
    -> compare predictions with reference evidence or observations
    -> flag uncertainties, contradictions and reproducibility limits
    -> researcher reviews findings and decides subsequent experiments
```

**Planned scientific capability areas**

| Area | Intended capability | Status |
|---|---|---|
| Physics and engineering | Invoke simulation engines and analyse results | Proposed; no integration |
| Chemistry | Use chemical datasets and computational analysis tools | Proposed; no integration |
| Instruments and sensors | Read measurements through authenticated, documented connectors | Proposed; no live connector |
| Mathematics and data science | Reproducible computations and statistical analysis | Proposed; no scientific execution engine |
| Scientific evidence | Source lineage, units, assumptions, methods, comparison and review | Existing legacy foundations only; migration pending |

Instrument control and any change to physical equipment must be explicitly authorised, policy-checked, independently interlocked where needed and reviewed by a qualified human operator. Start with **offline files, simulated instruments and read-only measurements**. An AI-generated command must never by itself authorise an experiment or device actuation.

## Non-negotiable migration rules

1. Migrate one bounded subsystem at a time.
2. Understand and document legacy behaviour before porting it.
3. Bring or rewrite tests with every migrated subsystem.
4. Keep policy, audit and execution responsibilities separate.
5. Never silently weaken approval, provenance or state-integrity guarantees.
6. Add regression tests for every known legacy failure being preserved against.
7. Test scientific unit correctness, reproducibility, unsafe action rejection and provenance before treating any scientific adapter as usable.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Migration manifest](docs/MIGRATION.md)
- [Security model](docs/SECURITY.md)
- [Training design](docs/TRAINING.md)
- [Contributing](CONTRIBUTING.md)
