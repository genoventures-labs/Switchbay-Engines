#!/usr/bin/env bash
# gumroad_cli_runner.sh — Switchbay GumOps shell wrapper
# All commands output JSON. Exit 0 = success, exit 1 = error.
# Usage: gumroad_cli_runner.sh <command> [args...]
# Commands: account | products | sales | sales_total | sale | top_products | payouts

set -euo pipefail
GUMROAD_BIN="${GUMROAD_BIN:-gumroad}"

die() { printf '{"success":false,"error":"%s"}\n' "$*" >&2; exit 1; }
require_bin() { command -v "$GUMROAD_BIN" >/dev/null 2>&1 || die "gumroad CLI not found"; }

cmd_account()  { "$GUMROAD_BIN" user --json; }
cmd_products() { "$GUMROAD_BIN" products list --json; }

cmd_sales() {
  local args=("--all" "--json")
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --after)   args+=("--after"   "$2"); shift 2 ;;
      --before)  args+=("--before"  "$2"); shift 2 ;;
      --product) args+=("--product" "$2"); shift 2 ;;
      --email)   args+=("--email"   "$2"); shift 2 ;;
      *) die "Unknown sales arg: $1" ;;
    esac
  done
  "$GUMROAD_BIN" sales list "${args[@]}"
}

cmd_sales_total() {
  local after="" before="" product=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --after)   after="$2";   shift 2 ;;
      --before)  before="$2";  shift 2 ;;
      --product) product="$2"; shift 2 ;;
      *) die "Unknown sales_total arg: $1" ;;
    esac
  done
  [[ -n "$after" ]] || die "sales_total requires --after DATE"
  command -v jq >/dev/null 2>&1 || die "jq required"

  local args=("--all" "--json" "--after" "$after")
  [[ -n "$before" ]]  && args+=("--before"  "$before")
  [[ -n "$product" ]] && args+=("--product" "$product")

  "$GUMROAD_BIN" sales list "${args[@]}" | jq '{
    success: true,
    sale_count: (.sales | map(select(.refunded == false)) | length),
    total_cents: (.sales | map(select(.refunded == false)) | map(.price // 0) | add // 0),
    total_formatted: ("$" + ((.sales | map(select(.refunded == false)) | map(.price // 0) | add // 0) / 100 | tostring))
  }'
}

cmd_sale() {
  local id="${1:-}"; [[ -n "$id" ]] || die "sale requires a sale ID"
  "$GUMROAD_BIN" sales list --order "$id" --json
}

cmd_top_products() {
  local after="" before=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --after)  after="$2";  shift 2 ;;
      --before) before="$2"; shift 2 ;;
      *) die "Unknown top_products arg: $1" ;;
    esac
  done
  command -v jq >/dev/null 2>&1 || die "jq required"

  local args=("--all" "--json")
  [[ -n "$after" ]]  && args+=("--after"  "$after")
  [[ -n "$before" ]] && args+=("--before" "$before")

  "$GUMROAD_BIN" sales list "${args[@]}" | jq '{
    success: true,
    products: (.sales | map(select(.refunded == false))
      | group_by(.product_name)
      | map({
          product: .[0].product_name,
          sales: length,
          total_cents: (map(.price // 0) | add // 0),
          total_formatted: ("$" + ((map(.price // 0) | add // 0) / 100 | tostring))
        })
      | sort_by(-.total_cents))
  }'
}

cmd_payouts() {
  "$GUMROAD_BIN" payouts --json 2>/dev/null || "$GUMROAD_BIN" payouts list --json
}

require_bin
COMMAND="${1:-}"; shift || true

case "$COMMAND" in
  account)      cmd_account "$@" ;;
  products)     cmd_products "$@" ;;
  sales)        cmd_sales "$@" ;;
  sales_total)  cmd_sales_total "$@" ;;
  sale)         cmd_sale "$@" ;;
  top_products) cmd_top_products "$@" ;;
  payouts)      cmd_payouts "$@" ;;
  "") die "No command. Use: account|products|sales|sales_total|sale|top_products|payouts" ;;
  *) die "Unknown command: $COMMAND" ;;
esac
