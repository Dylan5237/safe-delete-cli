#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

CONFIG="$TESTROOT/claude-settings.json"
INSTRUMENTED_CLI="$TESTROOT/instrumented-safe-delete"
CALLS="$TESTROOT/safe-delete-child-calls.log"
RAW_DIR="$TESTROOT/raw-command-sentinels"
RAW_MARKER="$TESTROOT/raw-command-used.log"
ADAPTER="$P6_XDG_DATA_HOME/safe-delete/hooks/v1/pretooluse"
p6_write_instrumented_cli "$INSTRUMENTED_CLI" "$CALLS"
p6_write_raw_sentinels "$RAW_DIR" "$RAW_MARKER"

printf '\n== init and install ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"
install_json="$(p6_cli hook install claude --config "$CONFIG" --cli "$INSTRUMENTED_CLI")"
printf '%s\n' "$install_json"
p6_assert_ok "$install_json"
[[ -x "$ADAPTER" ]]

HOOK_TARGET="$P6_WORKSPACE/composite-hook-target.txt"
COLLISION="$P6_WORKSPACE/composite-collision.txt"
printf 'composite hook fixture\n' >"$HOOK_TARGET"
REQUEST_JSON="$(python3 - "$HOOK_TARGET" "$P6_WORKSPACE" <<'PY'
import json
import sys

target, cwd = sys.argv[1:]
print(json.dumps({
    "protocol_version": 1,
    "request_id": "p6-composite-request",
    "tool": "claude-bash",
    "argv": ["rm", "--", target],
    "cwd": cwd,
    "project": cwd,
    "session_id": "p6-composite-session",
    "agent": "codex/luna",
    "reason": "p6 composite deletion",
}, separators=(",", ":")))
PY
)"
printf '\n== hook -> safe-delete add ==\nrequest=%s\n' "$REQUEST_JSON"
set +e
printf '%s' "$REQUEST_JSON" | env PATH="$RAW_DIR:$PATH" SAFE_DELETE_ROOT="$SAFE_DELETE_ROOT" "$ADAPTER" \
    >"$TESTROOT/hook.stdout" 2>"$TESTROOT/hook.stderr"
HOOK_EXIT=$?
set -e
HOOK_RESPONSE="$(<"$TESTROOT/hook.stdout")"
printf 'exit_code=%s\nresponse=%s\nchild_output=%s\n' "$HOOK_EXIT" "$HOOK_RESPONSE" "$(<"$TESTROOT/hook.stderr")"
[[ "$HOOK_EXIT" -eq 0 ]]
P6_JSON="$HOOK_RESPONSE" python3 - <<'PY'
import json
import os
response = json.loads(os.environ["P6_JSON"])
if response.get("decision") != "route" or response.get("reason_code") != "raw_delete":
    raise SystemExit(json.dumps(response, sort_keys=True))
PY
[[ ! -e "$HOOK_TARGET" ]]
[[ ! -e "$RAW_MARKER" ]]

ENTRY_ID="$(python3 - "$SAFE_DELETE_ROOT/ledger.jsonl" <<'PY'
import json
import sys

lines = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
if len(lines) != 1 or lines[0].get("operation") != "trash":
    raise SystemExit(repr(lines))
print(lines[0]["entry_id"])
PY
)"
printf 'hook_entry_id=%s\n' "$ENTRY_ID"

printf '\n== list and show ==\n'
list_json="$(p6_cli list)"
show_json="$(p6_cli show "$ENTRY_ID")"
printf 'list=%s\nshow=%s\n' "$list_json" "$show_json"
p6_assert_ok "$list_json"
p6_assert_ok "$show_json"
P6_LIST="$list_json" P6_SHOW="$show_json" P6_ENTRY_ID="$ENTRY_ID" python3 - <<'PY'
import json
import os

listing = json.loads(os.environ["P6_LIST"])
shown = json.loads(os.environ["P6_SHOW"])
entry_id = os.environ["P6_ENTRY_ID"]
if len(listing["results"]) != 1 or listing["results"][0]["entry_id"] != entry_id:
    raise SystemExit(json.dumps(listing, sort_keys=True))
if shown["results"][0]["state"] != "active":
    raise SystemExit(json.dumps(shown, sort_keys=True))
PY

printf 'collision sentinel\n' >"$COLLISION"
printf '\n== collision-safe restore refusal ==\n'
set +e
collision_json="$(p6_cli restore --to "$COLLISION" "$ENTRY_ID")"
collision_exit=$?
set -e
printf 'exit_code=%s\n%s\n' "$collision_exit" "$collision_json"
[[ "$collision_exit" -eq 3 ]]
p6_assert_error "$collision_json" destination_exists
[[ "$(<"$COLLISION")" == 'collision sentinel' ]]
[[ -e "$SAFE_DELETE_ROOT/trash/objects/$ENTRY_ID/payload" ]]

printf '\n== normal restore ==\n'
restore_json="$(p6_cli restore "$ENTRY_ID")"
printf '%s\n' "$restore_json"
p6_assert_ok "$restore_json"
[[ -f "$HOOK_TARGET" ]]
[[ ! -e "$SAFE_DELETE_ROOT/trash/objects/$ENTRY_ID/payload" ]]

PURGE_TARGET="$P6_WORKSPACE/composite-purge-target.txt"
printf 'composite purge fixture\n' >"$PURGE_TARGET"
candidate_json="$(p6_cli add --reason 'p6 composite purge' --tool 'safe-delete-cli' -- "$PURGE_TARGET")"
printf '\n== active candidate ==\n%s\n' "$candidate_json"
p6_assert_ok "$candidate_json"
CANDIDATE_ID="$(p6_result_field "$candidate_json" 0 entry_id)"
CANDIDATE_PAYLOAD="$(p6_result_field "$candidate_json" 0 trashed_path)"

printf '\n== controlled dry-run ==\n'
ledger_before="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"
dry_json="$(p6_cli purge --dry-run --older-than 1h)"
ledger_after="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"
printf '%s\nledger_sha256_before=%s\nledger_sha256_after=%s\n' "$dry_json" "$ledger_before" "$ledger_after"
p6_assert_ok "$dry_json"
[[ "$ledger_before" == "$ledger_after" ]]
[[ -f "$CANDIDATE_PAYLOAD" ]]
P6_JSON="$dry_json" P6_CANDIDATE_ID="$CANDIDATE_ID" python3 - <<'PY'
import json
import os
report = json.loads(os.environ["P6_JSON"])["results"][0]
candidate = os.environ["P6_CANDIDATE_ID"]
decision = next(item for item in report["decisions"] if item["entry_id"] == candidate)
if report["candidates"] != [] or decision.get("reason") != "too_young":
    raise SystemExit(json.dumps(report, sort_keys=True))
PY

CUTOFF="$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z"))')"
printf '\n== controlled execute cutoff=%s ==\n' "$CUTOFF"
execute_json="$(p6_cli purge --execute --yes --before "$CUTOFF")"
printf '%s\n' "$execute_json"
p6_assert_ok "$execute_json"
[[ ! -e "$CANDIDATE_PAYLOAD" ]]
[[ -f "$HOOK_TARGET" ]]

all_json="$(p6_cli list --all)"
printf '\n== final lifecycle inspection ==\n%s\n' "$all_json"
p6_assert_ok "$all_json"
P6_JSON="$all_json" P6_ENTRY_ID="$ENTRY_ID" P6_CANDIDATE_ID="$CANDIDATE_ID" python3 - <<'PY'
import json
import os

entries = {item["entry_id"]: item for item in json.loads(os.environ["P6_JSON"])["results"]}
if entries[os.environ["P6_ENTRY_ID"]]["state"] != "restored":
    raise SystemExit(repr(entries))
if entries[os.environ["P6_CANDIDATE_ID"]]["state"] != "purged":
    raise SystemExit(repr(entries))
PY

CALL_COUNT="$(wc -l <"$CALLS")"
LEDGER_COUNT="$(wc -l <"$SAFE_DELETE_ROOT/ledger.jsonl")"
printf '\nchild_call_count=%s\nledger_event_count=%s\nraw_fallback_marker=absent\n' "$CALL_COUNT" "$LEDGER_COUNT"
[[ "$CALL_COUNT" -eq 1 ]]
[[ "$LEDGER_COUNT" -eq 5 ]]
[[ ! -e "$RAW_MARKER" ]]
printf 'composite=hook->add->trash/ledger->list/show->collision-safe-restore->purge-dry-run/execute\n'
p6_finish_replay
