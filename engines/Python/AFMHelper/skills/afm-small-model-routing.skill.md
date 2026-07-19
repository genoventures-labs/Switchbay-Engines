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

## Use When

Use this engine when Switchbay is routing work to Apple's Foundation Models and the request is compound, context-heavy, schema-sensitive, or likely to produce malformed structured output.

## Tool Map

- `analyze_task`: size and route the request.
- `decompose_task`: turn compound work into short dependent steps.
- `build_context`: select relevant local chunks before prompting.
- `compile_prompt`: create a compact, explicit AFM prompt.
- `repair_json`: fix deterministic JSON defects.
- `validate_output`: enforce output contracts before downstream use.

## Method

Prefer deterministic preprocessing over asking AFM to infer hidden requirements. Keep one semantic objective per call. Supply only relevant context. Ask for exact formats. Validate before using the result as code, state, or tool input.

## Guardrails

This helper does not make AFM more knowledgeable and does not replace model-side safety or availability checks. Do not use it to silently truncate legally, medically, financially, or operationally critical source material. Surface truncation and split the task instead.
