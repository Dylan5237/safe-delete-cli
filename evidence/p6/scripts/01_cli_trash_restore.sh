#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

FILE="$P6_WORKSPACE/file.txt"
TREE="$P6_WORKSPACE/tree"
COLLISION="$P6_WORKSPACE/collision-target.txt"
mkdir -p -- "$TREE"
printf 'P6 file fixture\n' >"$FILE"
printf 'P6 directory fixture\n' >"$TREE/child.txt"

printf '\n== version before init ==\n'
version_json="$(p6_cli version)"
printf '%s\n' "$version_json"
p6_assert_ok "$version_json"
[[ ! -e "$SAFE_DELETE_ROOT" ]]

printf '\n== init ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"

printf '\n== add file and directory ==\n'
add_json="$(p6_cli add -- "$FILE" "$TREE")"
printf '%s\n' "$add_json"
p6_assert_ok "$add_json"
[[ ! -e "$FILE" ]]
[[ ! -e "$TREE" ]]
FILE_ID="$(p6_result_field "$add_json" 0 entry_id)"
TREE_ID="$(p6_result_field "$add_json" 1 entry_id)"
FILE_PAYLOAD="$(p6_result_field "$add_json" 0 trashed_path)"
TREE_PAYLOAD="$(p6_result_field "$add_json" 1 trashed_path)"
[[ -f "$FILE_PAYLOAD" ]]
[[ -d "$TREE_PAYLOAD" ]]

printf '\n== list ==\n'
list_json="$(p6_cli list)"
printf '%s\n' "$list_json"
p6_assert_ok "$list_json"

printf '\n== show file entry ==\n'
show_json="$(p6_cli show "$FILE_ID")"
printf '%s\n' "$show_json"
p6_assert_ok "$show_json"

printf '\n== orphan report ==\n'
orphans_json="$(p6_cli list --orphans)"
printf '%s\n' "$orphans_json"
p6_assert_ok "$orphans_json"

printf '\n== occupied destination refusal ==\n'
printf 'collision sentinel\n' >"$COLLISION"
set +e
collision_json="$(p6_cli restore --to "$COLLISION" "$FILE_ID")"
collision_code=$?
set -e
printf 'exit_code=%s\n%s\n' "$collision_code" "$collision_json"
[[ "$collision_code" -eq 3 ]]
p6_assert_error "$collision_json" destination_exists
[[ "$(cat -- "$COLLISION")" == 'collision sentinel' ]]
[[ -f "$FILE_PAYLOAD" ]]

printf '\n== restore file and directory ==\n'
restore_file_json="$(p6_cli restore "$FILE_ID")"
printf '%s\n' "$restore_file_json"
p6_assert_ok "$restore_file_json"
restore_tree_json="$(p6_cli restore "$TREE_ID")"
printf '%s\n' "$restore_tree_json"
p6_assert_ok "$restore_tree_json"
[[ -f "$FILE" ]]
[[ -f "$TREE/child.txt" ]]
[[ ! -e "$FILE_PAYLOAD" ]]
[[ ! -e "$TREE_PAYLOAD" ]]

printf '\n== lifecycle history ==\n'
all_json="$(p6_cli list --all)"
printf '%s\n' "$all_json"
p6_assert_ok "$all_json"
P6_JSON="$all_json" P6_FILE_ID="$FILE_ID" P6_TREE_ID="$TREE_ID" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["P6_JSON"])
expected = {os.environ["P6_FILE_ID"], os.environ["P6_TREE_ID"]}
entries = {item["entry_id"]: item for item in payload["results"]}
if set(entries) != expected or any(item["state"] != "restored" for item in entries.values()):
    raise SystemExit(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

printf '\nreplay_marker=PENDING_CAPTURE (local scaffold sanity path; not EVIDENCE READY)\n'
