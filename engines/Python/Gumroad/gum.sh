#!/usr/bin/env bash
# gum.sh — Switchbay shell wrapper for the Gumroad CLI
# All output is JSON. Structured for agent consumption.

set -euo pipefail

GUM="gumroad"
JSON_FLAG="--json"
NI="--non-interactive"

usage() {
  cat <<EOF
gum.sh — Gumroad CLI wrapper for Switchbay

Commands:
  summary [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--group-by product|day|week|month]
  sales   [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--product <id>] [--all]
  products
  product <id>
  user
  health
  refund  <sale_id>

Examples:
  ./gum.sh summary --from 2026-07-01 --to 2026-07-15
  ./gum.sh summary --group-by product
  ./gum.sh sales --after 2026-07-01 --all
  ./gum.sh health
EOF
  exit 0
}

require_gumroad() {
  if ! command -v "$GUM" &>/dev/null; then
    echo '{"error":"gumroad CLI not found","hint":"brew install antiwork/cli/gumroad"}' >&2
    exit 1
  fi
}

[[ $# -eq 0 ]] && usage

CMD="$1"; shift
require_gumroad

case "$CMD" in
  summary)
    $GUM sales summary $JSON_FLAG $NI "$@" 2>/dev/null
    ;;
  sales)
    $GUM sales list $JSON_FLAG $NI "$@" 2>/dev/null
    ;;
  products)
    $GUM products list $JSON_FLAG $NI "$@" 2>/dev/null
    ;;
  product)
    [[ $# -lt 1 ]] && echo '{"error":"product <id> required"}' >&2 && exit 1
    $GUM products view "$1" $JSON_FLAG $NI 2>/dev/null
    ;;
  user)
    $GUM user $JSON_FLAG $NI 2>/dev/null
    ;;
  health)
    if $GUM user $JSON_FLAG $NI &>/dev/null; then
      echo '{"status":"ok","cli":"gumroad","auth":"connected"}'
    else
      echo '{"status":"error","cli":"gumroad","auth":"failed"}'; exit 1
    fi
    ;;
  refund)
    [[ $# -lt 1 ]] && echo '{"error":"refund <sale_id> required"}' >&2 && exit 1
    $GUM sales refund "$1" $JSON_FLAG $NI --yes 2>/dev/null
    ;;
  *)
    echo "{\"error\":\"unknown command: $CMD\"}" >&2; exit 1
    ;;
esac
