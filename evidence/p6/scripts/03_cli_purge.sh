#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

RESTORED="$P6_WORKSPACE/restored-before-purge.txt"
CANDIDATE="$P6_WORKSPACE/purge-candidate.txt"

printf '\n== init ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"

printf '\n== create a restored exclusion ==\n'
printf 'this entry is restored and must remain ineligible\n' >"$RESTORED"
restored_add_json="$(p6_cli add -- "$RESTORED")"
printf '%s\n' "$restored_add_json"
p6_assert_ok "$restored_add_json"
RESTORED_ID="$(p6_result_field "$restored_add_json" 0 entry_id)"
restored_json="$(p6_cli restore "$RESTORED_ID")"
printf '%s\n' "$restored_json"
p6_assert_ok "$restored_json"

printf '\n== create an active purge candidate ==\n'
printf 'controlled purge fixture\n' >"$CANDIDATE"
candidate_add_json="$(p6_cli add -- "$CANDIDATE")"
printf '%s\n' "$candidate_add_json"
p6_assert_ok "$candidate_add_json"
CANDIDATE_ID="$(p6_result_field "$candidate_add_json" 0 entry_id)"
CANDIDATE_PAYLOAD="$(p6_result_field "$candidate_add_json" 0 trashed_path)"
[[ -f "$CANDIDATE_PAYLOAD" ]]

printf '\n== explicit dry-run with a short retention threshold ==\n'
ledger_before="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"
dry_json="$(p6_cli purge --dry-run --older-than 1h)"
printf '%s\n' "$dry_json"
p6_assert_ok "$dry_json"
ledger_after="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"
[[ "$ledger_before" == "$ledger_after" ]]
[[ -f "$CANDIDATE_PAYLOAD" ]]
P6_JSON="$dry_json" P6_CANDIDATE_ID="$CANDIDATE_ID" python3 - <<'PY'
import json
import os

report = json.loads(os.environ["P6_JSON"])["results"][0]
candidate_id = os.environ["P6_CANDIDATE_ID"]
if report["candidates"] != []:
    raise SystemExit(json.dumps(report, ensure_ascii=False, sort_keys=True))
decision = next(item for item in report["decisions"] if item["entry_id"] == candidate_id)
if decision.get("reason") != "too_young":
    raise SystemExit(json.dumps(report, ensure_ascii=False, sort_keys=True))
PY

printf '\n== controlled execute boundary ==\n'
CUTOFF="$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z"))')"
printf 'controlled_cutoff=%s\n' "$CUTOFF"
execute_json="$(p6_cli purge --execute --yes --before "$CUTOFF")"
printf '%s\n' "$execute_json"
p6_assert_ok "$execute_json"
[[ ! -e "$CANDIDATE_PAYLOAD" ]]
[[ -f "$RESTORED" ]]
P6_JSON="$execute_json" P6_CANDIDATE_ID="$CANDIDATE_ID" P6_RESTORED_ID="$RESTORED_ID" python3 - <<'PY'
import json
import os

report = json.loads(os.environ["P6_JSON"])["results"][0]
candidate_id = os.environ["P6_CANDIDATE_ID"]
restored_id = os.environ["P6_RESTORED_ID"]
outcomes = {item["entry_id"]: item for item in report["outcomes"]}
if outcomes[candidate_id].get("state") != "purged":
    raise SystemExit(json.dumps(report, ensure_ascii=False, sort_keys=True))
decisions = {item["entry_id"]: item for item in report["decisions"]}
if decisions[restored_id].get("reason") != "restored":
    raise SystemExit(json.dumps(report, ensure_ascii=False, sort_keys=True))
PY
grep -q '"operation":"purge_intent"' "$SAFE_DELETE_ROOT/ledger.jsonl"
grep -q '"operation":"purge_complete"' "$SAFE_DELETE_ROOT/ledger.jsonl"

printf '\n== post-purge inspection ==\n'
list_json="$(p6_cli list --all)"
printf '%s\n' "$list_json"
p6_assert_ok "$list_json"

printf '\nreplay_marker=PENDING_CAPTURE (local scaffold sanity path; not EVIDENCE READY)\n'
