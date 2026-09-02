# Training design

KobaldAi will not initially train a foundation model from random weights. The first
Kobald-specific model will adapt a suitable open-weight base model using verified
datasets and parameter-efficient training such as LoRA or QLoRA.

## Intended learning loop

```text
research task
  -> trainee model trajectory
  -> sources, claims, tool calls and outputs captured
  -> supervisor verification
  -> accepted/rejected steps with reasons
  -> scored immutable dataset example
  -> train/validation/test split
  -> candidate fine-tune
  -> capability and safety evaluation
  -> accept, reject or revise
  -> model registry
```

## Dataset requirements

Every accepted example must retain enough structured provenance to reproduce its
score. Dataset entries need model/base version, task definition, source identifiers,
tool definitions, important parameters, observations, verifier results and final
outcome. Secrets and irrelevant personal data must be excluded or redacted.

Rejected and failed trajectories are useful data, but must be labelled clearly and
must not be mixed into positive demonstrations as if they were correct.

## Evaluation gates

A candidate is not promoted merely because training loss fell. Evaluation must cover:

- research accuracy and citation support
- conflicting-information detection
- tool selection and argument validity
- adherence to asset authority and policy decisions
- resistance to prompt injection in sources and tool output
- recovery from tool and provider failures
- regression against previously fixed failures
- latency and memory use on intended Kobald hardware

Training infrastructure stays isolated from the production runtime. Models are
promoted through a registry with recorded data, configuration, evaluation and a
rollback target.
