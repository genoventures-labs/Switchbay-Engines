# Switchbay Engine Builder's Manual

How to build engines and `*.engine.json` manifests that models can actually call without breaking.

Use this when adding anything under `engines/` in this bay, or when dropping a local engine into `.switchbay/engines/`.

---

## What an engine is

An **engine** is:

1. One or more runnable scripts (Python / Node / Ruby / shell / etc.)
2. A `*.engine.json` manifest that maps **tool names → shell commands**
3. Optional skills / `AGENTS.md` that teach models *when* and *how* to use it

Switchbay discovers the manifest, shows tools to the model via `list_engines` / `list_engine_tools`, then runs them with `run_engine_tool`.

Models do **not** import your Python module. They only get whatever your CLI prints to **stdout** (prefer JSON).

---

## Minimum viable layout

```text
engines/<Lang>/<EngineName>/
  my_engine.py                 # CLI entrypoint(s)
  my_engine.engine.json        # required for discovery
  AGENTS.md                    # short human/agent notes (recommended)
  skills/
    my-engine-routing.skill.md # optional Switchbay skill
```

Register it in `switchbay.manifest.json` when shipping in this bay:

```json
{
  "id": "my-engine",
  "displayName": "My Engine",
  "path": "engines/Python/MyEngine/",
  "type": "python",
  "manifest": "engines/Python/MyEngine/my_engine.engine.json",
  "entrypoints": ["engines/Python/MyEngine/my_engine.py"],
  "skills": ["engines/Python/MyEngine/skills/my-engine-routing.skill.md"]
}
```

---

## Manifest schema (what Switchbay actually uses)

```json
{
  "id": "my-engine",
  "name": "My Engine",
  "description": "One sentence: what this engine does for the model.",
  "tools": [
    {
      "name": "status",
      "description": "Check the engine is reachable / configured.",
      "command": "python3 my_engine.py status --base_url {{base_url}}",
      "required": [],
      "parameters": {
        "base_url": {
          "type": "string",
          "description": "Optional origin. Omit to use env/config default.",
          "default": null
        }
      }
    }
  ],
  "approval": {
    "always": ["delete", "publish"]
  },
  "env": {},
  "data_dir": "~/.my_engine"
}
```

### Required fields

| Field | Rules |
|---|---|
| `id` | Letters, numbers, `_`, `-` only |
| `name` | Human label |
| `tools[]` | Non-empty array |
| `tools[].name` | Letters, numbers, `_`, `-` only |
| `tools[].command` | Shell command with `{{param}}` placeholders |

### Optional but important

| Field | Meaning |
|---|---|
| `description` | Shown in capability directory — write it for models |
| `cwd` | Working directory for commands. **If omitted, defaults to the folder that contains the `.engine.json`** |
| `tools[].required` | Param names that must be non-empty or Switchbay throws before running |
| `tools[].parameters` | Schema + docs for the model (defaults are **docs only** — see pitfalls) |
| `tools[].approval` | `"always"` on a single tool |
| `approval.always` | Substrings matched against tool name/command → force approval |
| `data_dir` | Documentation / convention for local state (not auto-mounted) |

---

## Golden rules (read these twice)

### 1. Command paths are relative to `cwd`

If you omit `cwd`, Switchbay sets it to the **manifest directory**.

**Do this (recommended for bay engines):**

```json
"command": "python3 my_engine.py status --flag {{flag}}"
```

**Do not do this** unless you also set `"cwd"` to the Engines repo root:

```json
"command": "python engines/Python/MyEngine/my_engine.py status"
```

That second form fails when cwd is `.../MyEngine/` because it looks for `MyEngine/engines/Python/MyEngine/...`.

Reference engines that get this right: WebSearch, PINATA, MemoryHelper, ResearchHelpers, PageTend.

### 2. Use `python3`, not `python`

On many Macs, `python` does not exist. Working bay engines use `python3` / `node` / explicit venv binaries.

### 3. Missing args become the string `None`

Switchbay template rendering:

- Missing / null / empty `{{param}}` → literal `None` (except `{{page}}` → `1`)
- Non-empty strings are shell-quoted
- Numbers/bools are stringified

Parameter `"default"` in the JSON schema is **not applied** before rendering. It only guides the model.

So this command:

```text
python3 tool.py run --days {{days}} --limit {{limit}}
```

with omitted args becomes:

```text
python3 tool.py run --days None --limit None
```

**Your CLI must accept that.**

Hardening pattern:

```python
def _noneish(value):
    if value is None:
        return None
    text = str(value).strip()
    return None if text in {"", "None", "null"} else text

def _parse_int(value, default, *, minimum=1, maximum=100):
    text = str(value).strip() if value is not None else ""
    if text in {"", "None", "null"}:
        return default
    try:
        return max(minimum, min(int(float(text)), maximum))
    except (TypeError, ValueError):
        return default

def _truthy(value, default=False):
    text = str(value).strip().lower() if value is not None else ""
    if text in {"", "none", "null"}:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
```

Also:

- Prefer `type=str` (or no type) for CLI flags that may receive `None`, then parse yourself
- Do **not** put optional enums in argparse `choices=` if Switchbay might pass `None` — validate in code instead

### 4. Print JSON on stdout; errors as JSON + exit 1

```python
print(json.dumps(result, indent=2, ensure_ascii=False))
# on failure:
print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
sys.exit(1)
```

Human-only `Created file.md` text is harder for models to consume.

### 5. Keep tools focused; return summaries for big payloads

Models drown in giant JSON. Pattern used by PageTend / Memory Helper:

- Default `--summary true`
- Put a compact `summary` (or `card`) object up front
- Keep full `data` available when needed

### 6. Approval for anything destructive or external-write

```json
"approval": {
  "always": ["delete_research_instance", "create_pdf", "publish_matrix"]
}
```

Or per-tool: `"approval": "always"`.

---

## Recommended CLI shape

```text
python3 my_engine.py <tool_name> --arg value ...
```

```python
def _cli() -> None:
    parser = argparse.ArgumentParser(...)
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("status")
    p.add_argument("--base_url", default=None)

    p = sub.add_parser("do_thing")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", default="12")  # string — harden None

    args = parser.parse_args()
    result = TOOLS[args.tool](**kwargs)
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

Subcommand names should match `tools[].name` exactly.

---

## Config & secrets

| Prefer | Avoid |
|---|---|
| Env vars (`PAGETEND_BASE_URL`, `GUMROAD_ACCESS_TOKEN`) | Hardcoding tokens in manifests |
| `~/.my_engine/config.json` | Committing secrets |
| Documenting config in `AGENTS.md` + skill | Empty env stubs that overwrite real values |

Manifest `"env": {}` is fine as documentation. Don't set `"TOKEN": ""` unless you intend to clear it.

---

## Skills (optional but high leverage)

Skills live as `*.skill.md` with YAML frontmatter. Put copies in:

- `engines/.../skills/` (ship with the engine)
- Engine Toolboxes `skills/` (for Switchbay toolbox sync)

Minimal frontmatter:

```yaml
---
id: my-engine-routing
name: My Engine Routing
description: When and how to use my-engine tools.
engine: my-engine
languages: [python]
agents: [any]
tags: [my-engine, switchbay-engine]
triggers: [phrase models should match]
---
```

Skill body should include: Use When, Tool map, Method, Output, Guardrails.

---

## Checklist before you ship

- [ ] `*.engine.json` validates (`id`, `name`, `tools`, each tool has `command`)
- [ ] Commands use `python3` / `node` and **manifest-relative** script paths (or an explicit correct `cwd`)
- [ ] Every optional `{{param}}` is safe when rendered as `None`
- [ ] Optional enum flags do not use argparse `choices=` that reject `None`
- [ ] Required params listed in `tools[].required`
- [ ] Destructive tools require approval
- [ ] CLI returns JSON; failure exits non-zero with `{"ok":false,"error":...}`
- [ ] Smoke-test from the manifest directory:

```bash
cd engines/Python/MyEngine
python3 my_engine.py status --base_url None
# Simulate omitted ints:
python3 my_engine.py do_thing --query "hi" --limit None
```

- [ ] Entry added to `switchbay.manifest.json` (bay engines)
- [ ] `AGENTS.md` + skill updated if models need routing help

---

## How models call your engine

1. `list_engines` → sees `id` + description  
2. `list_engine_tools` with `engine_id`  
3. `run_engine_tool` with `{ engine_id, tool_name, args_json }`  

Multi-engine use is already supported — models can call `pagetend`, then `memory-helper`, then `research-helpers` in the same session. Document companion engines in your skill; don't try to merge everything into one mega-engine.

---

## Common failure modes

| Symptom | Likely cause |
|---|---|
| `can't open file '.../MyEngine/engines/Python/...'` | Repo-root path with manifest-dir cwd |
| `command not found: python` | Use `python3` |
| `invalid int value: 'None'` | Optional int not hardened |
| `invalid choice: 'None'` | argparse `choices=` on optional enum |
| Tool runs but model ignores result | Non-JSON stdout |
| Wrong project memory / workspace | Forgot absolute `--workspace` |
| Writes without asking | Missing approval rules |

---

## Reference engines in this bay

| Engine | Good patterns to copy |
|---|---|
| `web-search` | Relative `python3` commands, clear required params |
| `pinata` | Multi-tool CLI, session store, approval on publish |
| `memory-helper` | On-demand recall, `None`-safe limits/scope |
| `research-helpers` | Multi-script engine, instance workspaces, approval on delete/PDF |
| `pagetend` | Summaries + cards, env/config base URL, rolling stats |

Templates: `template/default.engine.json`, `template/macos.engine.json`.

---

## Quick start stub

```bash
mkdir -p engines/Python/HelloHelper/skills
```

`hello_helper.py` — JSON CLI with a `status` + `greet` tool, `_noneish` / `_parse_int` helpers.

`hello_helper.engine.json`:

```json
{
  "id": "hello-helper",
  "name": "Hello Helper",
  "description": "Tiny example engine.",
  "tools": [
    {
      "name": "status",
      "description": "Confirm the engine runs.",
      "command": "python3 hello_helper.py status",
      "required": [],
      "parameters": {}
    },
    {
      "name": "greet",
      "description": "Greet someone.",
      "command": "python3 hello_helper.py greet --name {{name}} --times {{times}}",
      "required": ["name"],
      "parameters": {
        "name": { "type": "string", "description": "Who to greet." },
        "times": {
          "type": "integer",
          "description": "Repeat count. Default 1.",
          "default": 1
        }
      }
    }
  ],
  "approval": { "always": [] }
}
```

Then register it in `switchbay.manifest.json` and sync / reload engines in Switchbay.
