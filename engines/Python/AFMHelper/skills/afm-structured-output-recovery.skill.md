---
id: afm-structured-output-recovery
name: AFM Structured Output Recovery
description: Validate and deterministically repair common structured-output defects from Apple Foundation Models.
engine: afm-helper
languages: [python, swift]
agents: [any]
tags: [apple-foundation-models, afm, json, validation, repair, structured-output, small-model, switchbay-engine]
triggers: [repair AFM JSON, validate AFM output, malformed structured output, missing required fields, AFM schema check]
---

# AFM Structured Output Recovery

## Use When

- AFM must return JSON or another tightly constrained machine-consumed result.
- A model response may contain code fences, trailing commas, Python-style literals, or other deterministic JSON defects.
- Output must contain required fields or remain below an explicit size limit.
- A downstream tool, parser, state store, or application must not receive malformed model output.

## Tool Map

| Need | Tool |
|---|---|
| Check JSON validity, required fields, or size | `validate_output` |
| Repair supported deterministic JSON defects | `repair_json` |
| Recompile a clearer output contract | `compile_prompt` |
| Split an overloaded generation task | `decompose_task` |

## Method

1. Validate the raw model response before parsing it in application code or passing it downstream.
2. If validation succeeds, use the original output without rewriting it.
3. If validation fails because of a supported deterministic defect, call `repair_json` and validate the repaired result again.
4. Compare repaired structure with the requested contract. Repair syntax only; do not invent missing semantic content.
5. When required fields are absent, values are ambiguous, or the model ignored the contract, recompile a narrower prompt or regenerate only the failed section.
6. When repeated failures indicate too much work in one call, decompose the task and validate each smaller result independently.
7. Preserve the original response and the validation errors for debugging when the host application supports audit metadata.

## Output

Return or provide:

- **Status:** valid, repaired, or regeneration required.
- **Validation errors:** exact failed checks.
- **Repaired output:** only when deterministic repair succeeded and revalidation passed.
- **Semantic gaps:** missing or ambiguous content that repair cannot safely supply.
- **Next action:** accept, regenerate a narrow section, or decompose the task.

## Guardrails

- Never treat syntactically valid JSON as semantically correct without checking the requested fields and constraints.
- Do not fabricate values, fields, citations, identifiers, or decisions during repair.
- Do not silently coerce ambiguous data into a type that changes its meaning.
- Do not execute, persist, or forward output that still fails validation.
- Preserve a clear distinction between deterministic repair and model regeneration.