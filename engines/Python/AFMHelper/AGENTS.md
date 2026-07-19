# AFM Small Model Helper

Use this engine around Apple Foundation Models when a task benefits from deterministic preparation or validation.

Recommended flow:
1. `analyze_task` to decide single-pass vs stepwise execution.
2. `build_context` when the source material is larger than the useful context window.
3. `compile_prompt` to produce the final compact instruction sent to AFM.
4. Run AFM inside Switchbay.
5. `validate_output`; use `repair_json` when structured output is malformed.

This engine does not invoke AFM itself and requires no credentials, network access, or external API. It intentionally keeps retrieval, budgeting, decomposition, formatting, and validation deterministic.
