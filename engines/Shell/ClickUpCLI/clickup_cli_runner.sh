#!/usr/bin/env bash
# clickup_cli_runner.sh — Switchbay ClickUp CLI wrapper around `cup`
# All commands request JSON. Exit 0 = success, exit 1 = error.
#
# Usage:
#   ./clickup_cli_runner.sh <command> [args...]
#
# Commands:
#   status | auth | summary | assigned | overdue | inbox
#   sprint | sprints | spaces | members
#   tasks | search | task | activity | comments | subtasks
#   create | update | comment | assign | delete
#
# Notes:
#   - Switchbay may pass the literal string "None" for omitted optional args.
#   - Prefers CUP_BIN, then `cup` on PATH, then ~/.bun/bin/cup.

set -euo pipefail

CUP_BIN="${CUP_BIN:-}"
if [[ -z "$CUP_BIN" ]]; then
  if command -v cup >/dev/null 2>&1; then
    CUP_BIN="$(command -v cup)"
  elif [[ -x "${HOME}/.bun/bin/cup" ]]; then
    CUP_BIN="${HOME}/.bun/bin/cup"
  else
    CUP_BIN="cup"
  fi
fi

die() {
  # Escape for JSON string
  local msg
  msg=$(printf '%s' "$*" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])' 2>/dev/null || printf '%s' "$*" | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '{"ok":false,"error":"%s"}\n' "$msg" >&2
  exit 1
}

require_bin() {
  command -v "$CUP_BIN" >/dev/null 2>&1 || die "cup CLI not found (set CUP_BIN or install cup)"
}

# Switchbay interpolates missing optional params as the literal string "None".
is_none() {
  local v="${1:-}"
  [[ -z "$v" || "$v" == "None" || "$v" == "null" || "$v" == "NULL" ]]
}

# Append --flag value only when value is present (not None/empty).
opt_flag() {
  local flag="$1"
  local value="${2:-}"
  if ! is_none "$value"; then
    EXTRA_ARGS+=("$flag" "$value")
  fi
}

# Append bare flag when value is truthy.
opt_bool() {
  local flag="$1"
  local value="${2:-}"
  local lower
  lower=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    1|true|yes|on) EXTRA_ARGS+=("$flag") ;;
  esac
}

require_arg() {
  local name="$1"
  local value="${2:-}"
  if is_none "$value"; then
    die "$name is required"
  fi
}

# Run cup with optional EXTRA_ARGS inserted before trailing args (usually --json).
run_cup_extra() {
  local cmd="$1"
  shift
  if ((${#EXTRA_ARGS[@]})); then
    run_cup_raw "$cmd" "${EXTRA_ARGS[@]}" "$@"
  else
    run_cup_raw "$cmd" "$@"
  fi
}

run_cup_raw() {
  local errfile rc=0
  errfile="$(mktemp -t cup_cli.XXXXXX)"
  set +e
  "$CUP_BIN" "$@" 2>"$errfile"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    local err
    err="$(cat "$errfile" 2>/dev/null || true)"
    rm -f "$errfile"
    die "${err:-cup command failed: $*}"
  fi
  rm -f "$errfile"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_status() {
  if ! command -v "$CUP_BIN" >/dev/null 2>&1; then
    die "cup CLI not found"
  fi
  local version
  version=$("$CUP_BIN" --version 2>/dev/null || echo "unknown")
  # Try auth; still report status if auth fails. cup may exit 0 with authenticated:false.
  local auth_out=""
  auth_out=$("$CUP_BIN" auth --json 2>/dev/null || true)
  python3 - "$version" "$auth_out" <<'PY'
import json, sys
version, auth_out = sys.argv[1], sys.argv[2]
payload = {"ok": True, "tool": "status", "cup_bin": True, "version": version, "authenticated": False}
if auth_out.strip():
    try:
        auth = json.loads(auth_out)
        payload["auth"] = auth
        if isinstance(auth, dict) and auth.get("authenticated") is True:
            payload["authenticated"] = True
        elif isinstance(auth, dict) and auth.get("error"):
            payload["hint"] = "Run: cup init --token <TOKEN> --team <TEAM_ID>   or check network/CUP profile"
    except Exception:
        payload["auth_raw"] = auth_out[:500]
        payload["hint"] = "cup auth returned non-JSON; try: cup auth --json"
else:
    payload["hint"] = "Run: cup init --token <TOKEN> --team <TEAM_ID>   or check CUP profile"
print(json.dumps(payload, indent=2))
PY
}

cmd_auth() {
  run_cup_raw auth --json
}

cmd_summary() {
  EXTRA_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --hours) opt_flag --hours "${2:-}"; shift 2 ;;
      *) die "Unknown summary arg: $1" ;;
    esac
  done
  run_cup_extra summary --json
}

cmd_assigned() {
  run_cup_raw assigned --json
}

cmd_overdue() {
  run_cup_raw overdue --json
}

cmd_inbox() {
  run_cup_raw inbox --json
}

cmd_sprint() {
  run_cup_raw sprint --json
}

cmd_sprints() {
  run_cup_raw sprints --json
}

cmd_spaces() {
  run_cup_raw spaces --json
}

cmd_members() {
  run_cup_raw members --json
}

cmd_tasks() {
  EXTRA_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --status)   opt_flag --status "${2:-}"; shift 2 ;;
      --list)     opt_flag --list "${2:-}"; shift 2 ;;
      --space)    opt_flag --space "${2:-}"; shift 2 ;;
      --name)     opt_flag --name "${2:-}"; shift 2 ;;
      --assignee) opt_flag --assignee "${2:-}"; shift 2 ;;
      --tag)      opt_flag --tag "${2:-}"; shift 2 ;;
      --all)      opt_bool --all "${2:-true}"; shift 2 ;;
      --include-closed) opt_bool --include-closed "${2:-true}"; shift 2 ;;
      *) die "Unknown tasks arg: $1" ;;
    esac
  done
  run_cup_extra tasks --json
}

cmd_search() {
  local query=""
  EXTRA_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --query)    query="${2:-}"; shift 2 ;;
      --status)   opt_flag --status "${2:-}"; shift 2 ;;
      --list)     opt_flag --list "${2:-}"; shift 2 ;;
      --space)    opt_flag --space "${2:-}"; shift 2 ;;
      --assignee) opt_flag --assignee "${2:-}"; shift 2 ;;
      --tag)      opt_flag --tag "${2:-}"; shift 2 ;;
      --all)      opt_bool --all "${2:-true}"; shift 2 ;;
      --include-closed) opt_bool --include-closed "${2:-true}"; shift 2 ;;
      *)
        if is_none "$query"; then query="$1"; shift
        else die "Unknown search arg: $1"
        fi
        ;;
    esac
  done
  require_arg "query" "$query"
  if ((${#EXTRA_ARGS[@]})); then
    run_cup_raw search "$query" "${EXTRA_ARGS[@]}" --json
  else
    run_cup_raw search "$query" --json
  fi
}

cmd_task() {
  local task_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown task arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  run_cup_raw task "$task_id" --json
}

cmd_activity() {
  local task_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown activity arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  run_cup_raw activity "$task_id" --json
}

cmd_comments() {
  local task_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown comments arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  run_cup_raw comments "$task_id" --json
}

cmd_subtasks() {
  local task_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id|--parent) task_id="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown subtasks arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  run_cup_raw subtasks "$task_id" --json
}

cmd_create() {
  local list_id="" name="" description="" parent="" status="" priority="" assignee="" tags="" due=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --list|--list_id) list_id="${2:-}"; shift 2 ;;
      --name) name="${2:-}"; shift 2 ;;
      --description|--desc) description="${2:-}"; shift 2 ;;
      --parent|--parent_id) parent="${2:-}"; shift 2 ;;
      --status) status="${2:-}"; shift 2 ;;
      --priority) priority="${2:-}"; shift 2 ;;
      --assignee) assignee="${2:-}"; shift 2 ;;
      --tags) tags="${2:-}"; shift 2 ;;
      --due-date|--due) due="${2:-}"; shift 2 ;;
      *) die "Unknown create arg: $1" ;;
    esac
  done
  require_arg "name" "$name"
  EXTRA_ARGS=(create --name "$name")
  if ! is_none "$list_id"; then EXTRA_ARGS+=(--list "$list_id"); fi
  if ! is_none "$parent"; then EXTRA_ARGS+=(--parent "$parent"); fi
  if is_none "$list_id" && is_none "$parent"; then
    die "create requires --list (or sprint:current) or --parent for a subtask"
  fi
  if ! is_none "$description"; then EXTRA_ARGS+=(--description "$description"); fi
  if ! is_none "$status"; then EXTRA_ARGS+=(--status "$status"); fi
  if ! is_none "$priority"; then EXTRA_ARGS+=(--priority "$priority"); fi
  if ! is_none "$assignee"; then EXTRA_ARGS+=(--assignee "$assignee"); fi
  if ! is_none "$tags"; then EXTRA_ARGS+=(--tags "$tags"); fi
  if ! is_none "$due"; then EXTRA_ARGS+=(--due-date "$due"); fi
  EXTRA_ARGS+=(--json)
  run_cup_raw "${EXTRA_ARGS[@]}"
}

cmd_update() {
  local task_id="" status="" priority="" name="" description="" due=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      --status) status="${2:-}"; shift 2 ;;
      --priority) priority="${2:-}"; shift 2 ;;
      --name) name="${2:-}"; shift 2 ;;
      --description|--desc) description="${2:-}"; shift 2 ;;
      --due-date|--due) due="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown update arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  EXTRA_ARGS=(update "$task_id")
  local touched=false
  if ! is_none "$status"; then EXTRA_ARGS+=(--status "$status"); touched=true; fi
  if ! is_none "$priority"; then EXTRA_ARGS+=(--priority "$priority"); touched=true; fi
  if ! is_none "$name"; then EXTRA_ARGS+=(--name "$name"); touched=true; fi
  if ! is_none "$description"; then EXTRA_ARGS+=(--description "$description"); touched=true; fi
  if ! is_none "$due"; then EXTRA_ARGS+=(--due-date "$due"); touched=true; fi
  [[ "$touched" == true ]] || die "update requires at least one of --status --priority --name --description --due-date"
  EXTRA_ARGS+=(--json)
  run_cup_raw "${EXTRA_ARGS[@]}"
}

cmd_comment() {
  local task_id="" message=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      --message|--text) message="${2:-}"; shift 2 ;;
      *) die "Unknown comment arg: $1" ;;
    esac
  done
  require_arg "task_id" "$task_id"
  require_arg "message" "$message"
  run_cup_raw comment "$task_id" --message "$message" --json
}

cmd_assign() {
  local task_id="" assignee=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      --assignee|--to) assignee="${2:-}"; shift 2 ;;
      *) die "Unknown assign arg: $1" ;;
    esac
  done
  require_arg "task_id" "$task_id"
  require_arg "assignee" "$assignee"
  # cup assign uses --to
  run_cup_raw assign "$task_id" --to "$assignee" --json
}

cmd_delete() {
  local task_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task_id|--id) task_id="${2:-}"; shift 2 ;;
      *)
        if is_none "$task_id"; then task_id="$1"; shift
        else die "Unknown delete arg: $1"
        fi
        ;;
    esac
  done
  require_arg "task_id" "$task_id"
  run_cup_raw delete "$task_id" --confirm --json
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

require_bin
COMMAND="${1:-}"
shift || true

# Normalize Switchbay "None" command (shouldn't happen, but safe)
if is_none "$COMMAND"; then
  die "No command. Use: status|auth|summary|assigned|overdue|inbox|sprint|sprints|spaces|members|tasks|search|task|activity|comments|subtasks|create|update|comment|assign|delete"
fi

case "$COMMAND" in
  status)   cmd_status "$@" ;;
  auth)     cmd_auth "$@" ;;
  summary)  cmd_summary "$@" ;;
  assigned) cmd_assigned "$@" ;;
  overdue)  cmd_overdue "$@" ;;
  inbox)    cmd_inbox "$@" ;;
  sprint)   cmd_sprint "$@" ;;
  sprints)  cmd_sprints "$@" ;;
  spaces)   cmd_spaces "$@" ;;
  members)  cmd_members "$@" ;;
  tasks)    cmd_tasks "$@" ;;
  search)   cmd_search "$@" ;;
  task)     cmd_task "$@" ;;
  activity) cmd_activity "$@" ;;
  comments) cmd_comments "$@" ;;
  subtasks) cmd_subtasks "$@" ;;
  create)   cmd_create "$@" ;;
  update)   cmd_update "$@" ;;
  comment)  cmd_comment "$@" ;;
  assign)   cmd_assign "$@" ;;
  delete)   cmd_delete "$@" ;;
  help|-h|--help)
    cat <<'EOF'
clickup_cli_runner.sh — cup wrapper for Switchbay

Commands:
  status                 Check cup binary + auth
  auth                   Validate token / show user
  summary [--hours N]    Standup summary
  assigned               My tasks by status
  overdue                Overdue tasks
  inbox                  Recently updated tasks
  sprint / sprints       Active sprint / all sprints
  spaces / members       Workspace spaces / members
  tasks [filters]        List tasks (--status --list --space --name --assignee --tag --all)
  search --query TEXT    Search tasks
  task --task_id ID      Task details
  activity --task_id ID  Task + comments
  comments --task_id ID  List comments
  subtasks --task_id ID  List subtasks
  create ...             Create task/subtask (needs --list or --parent + --name)
  update --task_id ID    Update status/priority/name/description/due
  comment ...            Post comment (--task_id --message)
  assign ...             Assign (--task_id --assignee)
  delete --task_id ID    Delete task (destructive)

Omitted Switchbay args may arrive as "None" and are ignored for optional flags.
EOF
    ;;
  *) die "Unknown command: $COMMAND" ;;
esac
