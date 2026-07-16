# PINATA Research Workbench

Use this skill whenever the task involves Reddit-based product opportunity research using the PINATA engine.

## Use when:
- Finding product opportunities from Reddit pain signals
- Validating or stress-testing a product thesis
- Grouping pain signals into themes
- Scoring and comparing opportunity ideas
- Producing a final Winner / Next Up / Losers matrix

## Research Flow

This is a **deliberate, step-by-step workbench**. Never run all tools automatically. Let the human approve signals before they're saved. Let them review clusters before scoring. Let them narrate the matrix before publishing.

### Step 1 — Search
Use `search_reddit` with multiple query angles. The GPTInstructions system prompt defines good query patterns:
- Pain phrases: "frustrated with", "I hate", "takes hours", "wish there was"
- Behavior signals: "switching from", "alternative to", "manual process", "spreadsheet"
- Purchase signals: "would pay for", "too expensive", "missing feature"

Run **posts first**, then **comments** for the same topic. Vary subreddits. Compare recent vs older threads.

### Step 2 — Save Signals (human-approved)
After reviewing results, call `save_signal` only for items the human explicitly selects or approves.
- Assign meaningful tags: `pain`, `pricing`, `workaround`, `switching`, `missing_feature`, `frustration`
- Write a short note explaining why the signal is credible

Never auto-save all results. Quality over volume.

### Step 3 — Cluster
Call `cluster_signals` after enough signals are saved (≥5 recommended).
Present the clusters to the human. Ask if any labels need renaming before moving forward.

### Step 4 — Challenge the Thesis
Before scoring, always run `challenge_thesis` on each candidate opportunity.
Review the adversarial results carefully:
- High-scoring posts about existing happy users = red flag
- Mentions of free/cheap alternatives = pricing risk
- Low engagement on pain posts = weak demand signal

Report what you found, including anything that dents the thesis.

### Step 5 — Score
Use `score_opportunity` for each candidate. Score based on evidence from the session — not intuition.
Map your research findings to rubric dimensions:
- `pain_intensity`: How bad is the pain in the threads you read?
- `recurrence`: How many independent posts surfaced this same pain?
- `willingness_to_pay`: Did anyone mention budgets, pricing, or paying?
- `dissatisfaction`: How frustrated are users with current tools?
- `reachability`: Is there a clear subreddit, community, or channel to reach them?
- `competitive_whitespace`: Did challenge_thesis find strong existing solutions?
- `build_complexity`: Realistic effort estimate — 5 = weekend project, 1 = infra-heavy.

### Step 6 — Publish
Call `publish_matrix` only when the human says they're ready.
Write clear, honest narratives for Winner, Next Up, and Losers sections.
Include evidence gaps and confidence level in `research_notes`.

Output lands in `~/.pinata/opportunity_matrix.json` and `~/.pinata/opportunity_matrix.md`.

## Evidence Quality Rules (from GPTInstructions)

**Strong evidence:**
- Repeated pain across independent users
- Detailed descriptions with measurable costs (time, money)
- Active workarounds or tool-switching behavior
- Explicit budget discussion or willingness to pay
- Direct recommendation requests

**Weak evidence:**
- Jokes, vague dislike, hypothetical enthusiasm
- Isolated edge cases or user-error complaints
- Demand that only exists for a free product
- Single viral thread, single subreddit, single demographic

## Important Boundaries
- Never fabricate quotes, usernames, thread details, or consensus
- Use qualitative language when exact counts are unavailable
- Cite specific Reddit threads for important claims
- Separate: direct evidence / recurring pattern / inference / recommendation
- Always seek disconfirming evidence before concluding
