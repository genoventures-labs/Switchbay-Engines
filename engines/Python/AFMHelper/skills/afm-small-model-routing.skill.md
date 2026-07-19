---
id: afm-small-model-routing
name: AFM Small Model Routing
description: Prepare and validate tasks for Apple's on-device Foundation Models.
engine: afm-helper
languages: [python, swift]
agents: [any]
tags: [apple-foundation-models, afm, small-model, on-device, switchbay-engine]
triggers: [Apple Foundation Models, AFM, on-device model, small model, compact prompt, structured output repair]
---

# AFM Small Model Routing

## Use When

Use this engine when Switchbay is routing work to Apple's Foundation Models and the request is compound, context-heavy, schema-sensitive, or likely to produce malformed structured output.

## Tool Map

| Routing need | Tool |
|---|---|
| Size the task and choose single-pass or decomposition | `analyze_task` |
| Turn compound work into short dependent steps | `decompose_task` |
| Select relevant local chunks before prompting | `build_context` |
| Create a compact explicit AFM prompt | `compile_prompt` |
| Fix supported deterministic JSON defects | `repair_json` |
| Enforce output contracts before downstream use | `validate_output` |

## Method

1. Start with `analyze_task` when the request has multiple objectives, substantial context, or a strict output contract.
2. Use `decompose_task` when one AFM call would need to plan and execute several semantic operations.
3. Use `build_context` before prompting when the available source material exceeds the useful context budget.
4. Use `compile_prompt` to preserve one objective, explicit constraints, and an exact output contract.
5. Run AFM through the host application or Switchbay route; this helper does not invoke the model itself.
6. Call `validate_output` before using the response as code, persistent state, or tool input.
7. Use `repair_json` only for supported deterministic defects, then validate again.

## Output

Return or present:

- **Route:** the selected execution path and tools.
- **Reason:** the task pressure or failure mode driving that route.
- **Prepared input:** selected context and compiled prompt when applicable.
- **Validation result:** whether output is accepted, repaired, or requires regeneration.
- **Limitations:** truncation, unresolved ambiguity, or host-side AFM requirements.

## Guardrails

- This helper does not make AFM more knowledgeable and does not replace model-side safety or availability checks.
- Do not silently truncate legally, medically, financially, security, or operationally critical source material. Surface truncation and split the task instead.
- Do not ask AFM to perform deterministic parsing, sorting, filtering, counting, or schema validation when code can do it exactly.
- Do not pass malformed or unvalidated model output into downstream tools or persistent state.
- Do not claim that the engine invokes AFM; model execution remains the host application's responsibility.