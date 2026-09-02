# Security model

KobaldAi can eventually operate tools and managed systems. Security boundaries are
therefore part of its architecture, not an optional hardening pass.

## Principles

- Deny state-changing actions by default until authority is established.
- Treat model output, retrieved text, tool output and network data as untrusted.
- Separate the component proposing an action from the component authorising it.
- Bind approvals to the exact action, target, important parameters and expiry.
- Record decisions and outcomes without storing raw secrets or unnecessary prompts.
- Prefer least-privilege integration credentials and constrained tool interfaces.
- Reconcile interrupted actions before retrying anything that might have changed state.
- Fail closed when policy, state-integrity or authority information is unavailable.

## Asset registry

Managed assets require stable identity, ownership, environment, allowed capabilities
and policy profile. An IP address being on Cameron's network or remembered by a
model does not prove ownership or authority. The registry supplies local context so
Kobald can avoid pointless repeated questioning while retaining enforceable scope.

## Secrets and runtime data

Credentials, signing keys, local config, runtime state, audit logs, datasets and
model artefacts must remain outside Git. Example configuration contains no real
credentials. Logs should use identifiers and redaction instead of raw secrets.

## Reporting a vulnerability

Do not publish a working exploit or real credentials in a public issue. Open a
minimal issue stating that a private security report is needed, without including
the sensitive details, until a dedicated private reporting channel is configured.

## Current limitations

This repository currently contains architecture and foundation scaffolding only.
No claim is made that the legacy security mechanisms have been migrated or verified.
