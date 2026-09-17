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

printf '\n== init ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"

printf '\n== install real PreToolUse adapter into disposable config ==\n'
install_json="$(p6_cli hook install claude --config "$CONFIG" --cli "$INSTRUMENTED_CLI")"
printf '%s\n' "$install_json"
p6_assert_ok "$install_json"
[[ -x "$ADAPTER" ]]
P6_JSON="$install_json" python3 - <<'PY'
import json
import os

result = json.loads(os.environ["P6_JSON"])["results"][0]
if not result.get("enforced") or result.get("boundary", {}).get("registered") is not True:
    raise SystemExit(json.dumps(result, sort_keys=True))
PY

p6_request() {
    local command="$1"
    local target="$2"
    python3 - "$command" "$target" "$P6_WORKSPACE" <<'PY'
import json
import sys

command, target, cwd = sys.argv[1:]
if command == "rm":
    argv = ["rm", "-rf", "--", target]
elif command == "unlink":
    argv = ["unlink", "--", target]
elif command == "rmdir":
    argv = ["rmdir", "--", target]
else:
    raise SystemExit(f"unsupported test command: {command}")
print(json.dumps({
    "protocol_version": 1,
    "request_id": f"p6-pretooluse-{command}",
    "tool": "claude-bash",
    "argv": argv,
    "cwd": cwd,
    "project": cwd,
    "session_id": "p6-pretool-session",
    "agent": "codex/luna",
    "reason": "p6 hook replay",
    "extensions": {"evidence": {"phase": 6, "route": "pretooluse"}},
}, separators=(",", ":")))
PY
}

run_request() {
    local command="$1"
    local target="$2"
    local stdout_file="$TESTROOT/${command}.stdout"
    local stderr_file="$TESTROOT/${command}.stderr"
    local request_json
    request_json="$(p6_request "$command" "$target")"
    printf '\n== PreToolUse %s ==\nrequest=%s\n' "$command" "$request_json"
    set +e
    printf '%s' "$request_json" | env PATH="$RAW_DIR:$PATH" SAFE_DELETE_ROOT="$SAFE_DELETE_ROOT" "$ADAPTER" >"$stdout_file" 2>"$stderr_file"
    local exit_code=$?
    set -e
    local response="$(<"$stdout_file")"
    printf 'exit_code=%s\nadapter_stdout=%s\nadapter_stderr=%s\n' \
        "$exit_code" "$response" "$(<"$stderr_file")"
    [[ "$exit_code" -eq 0 ]]
    P6_JSON="$response" P6_COMMAND="$command" python3 - <<'PY'
import json
import os

response = json.loads(os.environ["P6_JSON"])
if response.get("decision") != "route" or response.get("reason_code") != "raw_delete":
    raise SystemExit(json.dumps(response, sort_keys=True))
if response.get("request_id") != f"p6-pretooluse-{os.environ['P6_COMMAND']}":
    raise SystemExit(json.dumps(response, sort_keys=True))
PY
}

FILE="$P6_WORKSPACE/pretooluse-file.txt"
UNLINK_FILE="$P6_WORKSPACE/pretooluse-unlink.txt"
DIRECTORY="$P6_WORKSPACE/pretooluse-directory"
printf 'pretooluse file\n' >"$FILE"
printf 'pretooluse unlink\n' >"$UNLINK_FILE"
mkdir -- "$DIRECTORY"

run_request rm "$FILE"
run_request unlink "$UNLINK_FILE"
run_request rmdir "$DIRECTORY"

[[ ! -e "$FILE" && ! -e "$UNLINK_FILE" && ! -e "$DIRECTORY" ]]
[[ ! -e "$RAW_MARKER" ]]
CALL_COUNT="$(wc -l <"$CALLS")"
LEDGER_COUNT="$(wc -l <"$SAFE_DELETE_ROOT/ledger.jsonl")"
printf '\nchild_call_count=%s\nledger_event_count=%s\nraw_fallback_marker=absent\nchild_calls:\n%s\n' \
    "$CALL_COUNT" "$LEDGER_COUNT" "$(<"$CALLS")"
[[ "$CALL_COUNT" -eq 3 ]]
[[ "$LEDGER_COUNT" -eq 3 ]]
P6_CALLS="$CALLS" P6_LEDGER="$SAFE_DELETE_ROOT/ledger.jsonl" python3 - <<'PY'
import json
import os

calls = open(os.environ["P6_CALLS"], encoding="utf-8").read().splitlines()
if len(calls) != 3 or any("--tool pretooluse:claude-bash" not in line for line in calls):
    raise SystemExit(repr(calls))
events = [json.loads(line) for line in open(os.environ["P6_LEDGER"], encoding="utf-8")]
if len(events) != 3 or any(event.get("operation") != "trash" for event in events):
    raise SystemExit(repr(events))
if any(event.get("session_id") != "p6-pretool-session" or event.get("agent") != "codex/luna" for event in events):
    raise SystemExit(repr(events))
PY

printf 'raw_deletion_not_executed=true\n'
p6_finish_replay
