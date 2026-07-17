## ResearchHelpers Engine

## What is this?
Research and analysis helpers for Switchbay: manage research instances, structure research tasks, visualize and model data, and write research artifacts across common document formats.

## Tools
- `create_research_instance` / `list_research_instances` / `get_research_instance` / `update_research_instance` / `delete_research_instance` — Named research projects with local workspaces under `~/.research_instances/`.
- `research_assistant` — Structure a research task into a brief/plan with keywords, questions, search angles, and optional seed web sources. Session: `~/.research_assistant/session.json`.
- `data_visualization` — Chart structured data (spec / ASCII / SVG / HTML / PNG).
- `data_modeling` — Lightweight stats: summary, correlation, regression/trend, forecast.
- `create_markdown` / `create_pdf` / `create_docx` / `create_html` / `create_txt` — Write research artifacts via `artifact_creation.py`.

## Notes
- Typical flow: create an instance → run `research_assistant` / Web Search / PINATA → update the instance with notes & sources → write artifacts into the instance workspace `artifacts/` folder.
- Artifact PDF/DOCX need optional deps: `reportlab`, `python-docx`. PNG charts need `matplotlib`.
- Engine id: `research-helpers`.
