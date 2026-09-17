#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

INSTRUMENTED_CLI="$TESTROOT/instrumented-safe-delete"
CALLS="$TESTROOT/safe-delete-child-calls.log"
RAW_DIR="$TESTROOT/raw-command-sentinels"
RAW_MARKER="$TESTROOT/raw-command-used.log"
ORIGINAL_PATH="$PATH"

p6_write_instrumented_cli "$INSTRUMENTED_CLI" "$CALLS"
p6_write_raw_sentinels "$RAW_DIR" "$RAW_MARKER"

printf '\n== init ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"

printf '\n== install real PATH shims ==\n'
install_json="$(p6_cli hook install path-shim --cli "$INSTRUMENTED_CLI")"
printf '%s\n' "$install_json"
p6_assert_ok "$install_json"
SHIM_DIR="$P6_XDG_DATA_HOME/safe-delete/bin"
for command in rm unlink rmdir; do
    [[ -x "$SHIM_DIR/$command" ]]
done

status_json="$(PATH="$SHIM_DIR:$ORIGINAL_PATH" p6_cli hook status path-shim)"
printf '\n== status with shim first on PATH ==\n%s\n' "$status_json"
p6_assert_ok "$status_json"
P6_JSON="$status_json" P6_SHIM_DIR="$SHIM_DIR" python3 - <<'PY'
import json
import os

result = json.loads(os.environ["P6_JSON"])["results"][0]
if not result.get("enforced") or result.get("boundary", {}).get("path_precedence") is not True:
    raise SystemExit(json.dumps(result, sort_keys=True))
if result.get("boundary", {}).get("prepend_path") != os.environ["P6_SHIM_DIR"]:
    raise SystemExit(json.dumps(result, sort_keys=True))
PY

run_shim() {
    local command="$1"
    local target="$2"
    shift 2
    local stdout_file="$TESTROOT/${command}.stdout"
    local stderr_file="$TESTROOT/${command}.stderr"
    local resolved
    resolved="$(PATH="$SHIM_DIR:$RAW_DIR:$ORIGINAL_PATH" command -v "$command")"
    printf '\n== PATH shim %s ==\nresolved=%s\nargv=%s\n' "$command" "$resolved" "$* $target"
    [[ "$resolved" == "$SHIM_DIR/$command" ]]
    set +e
    PATH="$SHIM_DIR:$RAW_DIR:$ORIGINAL_PATH" \
        SAFE_DELETE_ROOT="$SAFE_DELETE_ROOT" \
        SAFE_DELETE_PROJECT="$P6_WORKSPACE" \
        SAFE_DELETE_SESSION_ID="p6-path-session" \
        SAFE_DELETE_AGENT="codex/luna" \
        "$command" "$@" "$target" >"$stdout_file" 2>"$stderr_file"
    local exit_code=$?
    set -e
    printf 'exit_code=%s\nstdout=%s\nstderr=%s\n' "$exit_code" "$(<"$stdout_file")" "$(<"$stderr_file")"
    [[ "$exit_code" -eq 0 ]]
}

RM_TARGET="$P6_WORKSPACE/path-rm.txt"
UNLINK_TARGET="$P6_WORKSPACE/path-unlink.txt"
RMDIR_TARGET="$P6_WORKSPACE/path-rmdir"
printf 'path rm\n' >"$RM_TARGET"
printf 'path unlink\n' >"$UNLINK_TARGET"
mkdir -- "$RMDIR_TARGET"

run_shim rm "$RM_TARGET" -R -f --
run_shim unlink "$UNLINK_TARGET" --
run_shim rmdir "$RMDIR_TARGET" --

[[ ! -e "$RM_TARGET" && ! -e "$UNLINK_TARGET" && ! -e "$RMDIR_TARGET" ]]
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
expected_tools = {"--tool path-shim:rm", "--tool path-shim:unlink", "--tool path-shim:rmdir"}
if len(calls) != 3 or not all(any(tool in line for tool in expected_tools) for line in calls):
    raise SystemExit(repr(calls))
events = [json.loads(line) for line in open(os.environ["P6_LEDGER"], encoding="utf-8")]
if len(events) != 3 or any(event.get("operation") != "trash" for event in events):
    raise SystemExit(repr(events))
if any(event.get("session_id") != "p6-path-session" or event.get("agent") != "codex/luna" for event in events):
    raise SystemExit(repr(events))
PY

printf 'raw_deletion_not_executed=true\n'
p6_finish_replay
