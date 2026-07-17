---
id: research-helpers-workflow
name: Research Helpers Workflow
description: Run structured research in Switchbay — create instances, brief tasks, gather sources, visualize/model data, and ship artifacts without dumping everything into one giant turn.
engine: research-helpers
languages: [python]
agents: [any]
tags: [research, instances, brief, visualization, modeling, artifacts, reports, switchbay-engine]
triggers: [research, research instance, research brief, research plan, visualize data, data model, write report, markdown report, pdf report, artifact, investigate topic]
---

# Research Helpers Workflow

## Use When

- The user wants a structured research task, brief, plan, or report.
- You need a durable research “project” (instance) with notes, sources, and a workspace.
- Data needs a quick chart, summary stats, correlation, regression, or naive forecast.
- You should write a deliverable (md/pdf/docx/html/txt) from findings.

## Engine

- Engine id: `research-helpers`
- Call via `list_engine_tools` → `run_engine_tool`
- Pair with `web-search`, built-in Web Engine, `pinata`, and `memory-helper` when deeper evidence or recall is needed

## Tool Map

### Instances (durable projects)

| Tool | Purpose | Approval? |
|---|---|---|
| `create_research_instance` | Named project + workspace under `~/.research_instances/` | No |
| `list_research_instances` | List/filter instances | No |
| `get_research_instance` | Full instance (notes, sources, workspace path) | No |
| `update_research_instance` | Description, status, tags, rename, append note/source | No |
| `delete_research_instance` | Remove instance (+ workspace unless kept) | **Yes** |

### Assist / analyze

| Tool | Purpose | Approval? |
|---|---|---|
| `research_assistant` | Task → brief/plan/notes/report + optional seed web sources | No |
| `data_visualization` | Chart data (spec/ascii/svg/html/png) | No |
| `data_modeling` | summary / correlation / regression / trend / forecast | No |

### Artifacts

| Tool | Purpose | Approval? |
|---|---|---|
| `create_markdown` | Structured markdown report | No |
| `create_html` / `create_txt` | HTML or plain text artifact | No |
| `create_pdf` | PDF (needs `reportlab`) | **Yes** |
| `create_docx` | DOCX (needs `python-docx`) | **Yes** |

## Method

### Default research flow

1. **Open or create an instance**
   - `list_research_instances` (filter by tag/status/query) before creating duplicates.
   - `create_research_instance` with a clear `name`, `description`, and tags.
   - Optional: opening `note` and first `source_url`.

2. **Structure the task**
   - `research_assistant` with `task`, optional `context`, and `output_type`:
     - `brief` / `json` — structured plan object (default)
     - `plan` — steps + questions + search angles
     - `notes` — checklist-style notes
     - `report` — markdown draft written under `~/.research_assistant/outputs/`
   - Keep `search: true` for seed sources unless offline / user asked not to.

3. **Gather evidence (companion engines)**
   - Use `web-search` / Web Engine for deeper fetch after seed sources.
   - Use `pinata` only for Reddit opportunity research.
   - Use `memory-helper` if prior workspace/session memory matters.
   - After each useful find, `update_research_instance` with `--note` and/or `--source_url`.

4. **Analyze data when present**
   - `data_modeling` first for summary/correlation/regression.
   - `data_visualization` for charts (`ascii` for quick replies; `svg`/`html`/`png` for artifacts).
   - Pass JSON arrays, object-of-series, array-of-objects, or simple CSV.

5. **Ship a deliverable**
   - Prefer writing into the instance workspace `artifacts/` folder when you have the path from `get_research_instance`.
   - Use `create_markdown` for the default report; escalate to PDF/DOCX only when asked (approval required).
   - Update instance status: `active` → `done` (or `paused` / `archived`).

### Status vocabulary

`active` · `paused` · `archived` · `done`

## Output

- Instance id/name/workspace path when creating or updating.
- Research brief/plan with questions, search angles, and seed sources.
- Model/viz results as tables, equations, or chart paths — not vague summaries alone.
- Artifact filename/path on success; clear dependency error if PDF/DOCX/PNG libs are missing.
- Separate **direct evidence / pattern / inference / recommendation** in narrative answers.

## Guardrails

- Do not invent sources, quotes, stats, or “memory” of research that was not returned by a tool.
- Seed DuckDuckGo results are best-effort snippets — verify important claims with scrape/fetch before concluding.
- Never auto-delete instances; `delete_research_instance` requires approval.
- Do not run PDF/DOCX creation unless the user wants that format.
- Keep instance notes short and dated; put long writeups in artifacts, not the note stream.
- Naive `forecast` is linear extrapolation only — say so when presenting it.
