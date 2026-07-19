---
id: afm-task-decomposition
name: AFM Task Decomposition
description: Break compound work into small ordered calls that fit Apple Foundation Models reliably.
engine: afm-helper
languages: [python, swift]
agents: [any]
tags: [apple-foundation-models, afm, decomposition, planning, small-model, on-device, switchbay-engine]
triggers: [decompose for AFM, split small model task, AFM task planning, reduce prompt complexity, one objective per call]
---

# AFM Task Decomposition

## Use When

- A request contains multiple deliverables, transformations, decisions, or dependent steps.
- `analyze_task` reports elevated ambiguity, context pressure, or compound-job risk.
- A single AFM call would require the model to plan, execute, validate, and format simultaneously.
- The work can be made more reliable by giving each model call one semantic objective.

## Tool Map

| Need | Tool |
|---|---|
| Estimate task pressure and choose a route | `analyze_task` |
| Produce short ordered execution steps | `decompose_task` |
| Prepare each resulting model call | `compile_prompt` |
| Check the result before advancing | `validate_output` |

## Method

1. Run `analyze_task` on the complete request before removing details or rewriting it.
2. Keep a single call only when the task has one clear objective, modest context, and a simple output contract.
3. Otherwise call `decompose_task` and preserve dependencies between steps.
4. Each step should have one primary objective, explicit inputs, an expected output, and a clear reason it must occur at that point.
5. Keep deterministic work outside AFM. Parsing, sorting, filtering, counting, schema checks, and exact formatting should remain in code or engine tools.
6. Compile a separate compact prompt for each model-required step.
7. Validate each output before passing it into the next step. Do not let malformed or incomplete intermediate output silently contaminate downstream work.

## Output

Return or present:

- **Route:** single-pass or decomposed.
- **Reason:** the strongest pressure signal, such as ambiguity, context size, or multiple objectives.
- **Steps:** ordered model and deterministic operations with dependencies.
- **Validation points:** where output must be checked before continuation.
- **Fallback:** how to split again or surface missing information if a step fails.

## Guardrails

- Do not split a task merely to create more model calls; decomposition must reduce ambiguity or execution risk.
- Do not discard user constraints while simplifying a step.
- Do not ask AFM to perform deterministic operations that the engine or host application can perform exactly.
- Do not pass an unvalidated model result into code execution, persistent state, or another tool.
- Clearly surface unresolved dependencies instead of inventing missing inputs.