#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

PROJECT="$P6_WORKSPACE/project"
FILE="$P6_WORKSPACE/metadata.txt"
NO_CONTEXT="$P6_WORKSPACE/no-context.txt"
EXTENSIONS='{"nested":{"source":"p6-scaffold","values":["one",2,true]}}'
NO_CONTEXT_CWD="${P6_NO_CONTEXT_CWD:-/var}"
[[ -d "$NO_CONTEXT_CWD" ]]
mkdir -p -- "$PROJECT"
printf 'rich metadata fixture\n' >"$FILE"
printf 'no context fixture\n' >"$NO_CONTEXT"

printf '\n== init ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"

printf '\n== add with all six rich inputs ==\n'
rich_json="$(p6_cli add \
    --reason 'retention review' \
    --project "$PROJECT/." \
    --session-id 'session-p6-42' \
    --agent 'luna' \
    --tool 'safe-delete-cli' \
    --extensions "$EXTENSIONS" \
    -- "$FILE")"
printf '%s\n' "$rich_json"
p6_assert_ok "$rich_json"
RICH_ID="$(p6_result_field "$rich_json" 0 entry_id)"
P6_JSON="$rich_json" P6_PROJECT="$PROJECT" P6_EXTENSIONS="$EXTENSIONS" python3 - <<'PY'
import json
import os

result = json.loads(os.environ["P6_JSON"])["results"][0]
expected_extensions = json.loads(os.environ["P6_EXTENSIONS"])
expected = {
    "project": os.environ["P6_PROJECT"],
    "session_id": "session-p6-42",
    "reason": "retention review",
    "agent": "luna",
    "tool": "safe-delete-cli",
    "extensions": expected_extensions,
}
observed = {key: result.get(key) for key in expected}
if observed != expected:
    raise SystemExit(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

printf '\n== show and normalized project filter ==\n'
show_json="$(p6_cli show "$RICH_ID")"
printf '%s\n' "$show_json"
p6_assert_ok "$show_json"
filtered_json="$(p6_cli list --project "$PROJECT")"
printf '%s\n' "$filtered_json"
p6_assert_ok "$filtered_json"

printf '\n== absent context does not fabricate identity ==\n'
set +u
absent_json="$(
    # Invoke outside the checkout and its /tmp test-parent so project detection
    # has no supported repository root to discover.
    cd -- "$NO_CONTEXT_CWD"
    env -u SAFE_DELETE_PROJECT -u SAFE_DELETE_SESSION_ID -u SAFE_DELETE_AGENT \
        "$CHECKOUT/safe-delete" --root "$SAFE_DELETE_ROOT" --json add -- "$NO_CONTEXT"
)"
set -u
printf '%s\n' "$absent_json"
p6_assert_ok "$absent_json"
P6_JSON="$absent_json" python3 - <<'PY'
import json
import os

result = json.loads(os.environ["P6_JSON"])["results"][0]
expected_null = ("project", "session_id", "reason", "agent", "extensions")
if any(result.get(key) is not None for key in expected_null):
    raise SystemExit(json.dumps(result, ensure_ascii=False, sort_keys=True))
if result.get("tool") != "safe-delete-cli":
    raise SystemExit(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

printf '\nreplay_marker=PENDING_CAPTURE (local scaffold sanity path; not EVIDENCE READY)\n'
