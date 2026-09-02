# Contributing

KobaldAi is being migrated deliberately from a legacy prototype. A change is not
complete merely because equivalent legacy code has been copied into this repository.

## Workflow

1. Choose a bounded item from `docs/MIGRATION.md` or `docs/ROADMAP.md`.
2. Record the legacy files, behaviours and relevant tests being assessed.
3. Write or update the target design before implementing substantial behaviour.
4. Port or rewrite the subsystem without unrelated changes.
5. Add unit, integration and regression tests.
6. Run Ruff, mypy and pytest locally.
7. Update the migration manifest with evidence and any deliberate differences.

## Completion standard

A migrated subsystem must have:

- a clear public interface
- typed inputs and outputs
- documented trust and failure boundaries
- tests for success, rejection and failure paths
- no implicit dependency on GUI or transport layers
- no secrets, credentials or live runtime data committed

Do not claim feature parity until its behaviour has been compared against the
legacy implementation and the result is recorded in `docs/MIGRATION.md`.
