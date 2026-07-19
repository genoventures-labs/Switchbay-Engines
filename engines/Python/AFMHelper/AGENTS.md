# AFM Small Model Helper

Use this engine around Apple Foundation Models when a task benefits from deterministic preparation or validation.

Recommended flow:
1. `analyze_task` to decide single-pass vs stepwise execution.
2. `decompose_task` when the request contains multiple semantic objectives or dependent deliverables.
3. `build_context` when the source material is larger than the useful context window.
4. `compile_prompt` to produce the final compact instruction sent to AFM.
5. Run AFM inside the host application or Switchbay route.
6. `validate_output`; use `repair_json` when structured output has a supported deterministic defect.

Skills:
- `afm-small-model-routing.skill.md` — broad engine routing and end-to-end flow.
- `afm-task-decomposition.skill.md` — compound-task analysis, ordered steps, and validation boundaries.
- `afm-context-prompt-compilation.skill.md` — context selection, prompt compilation, and truncation disclosure.
- `afm-structured-output-recovery.skill.md` — validation, deterministic JSON repair, and regeneration decisions.

This engine does not invoke AFM itself and requires no credentials, network access, or external API. It intentionally keeps retrieval, budgeting, decomposition, formatting, and validation deterministic.