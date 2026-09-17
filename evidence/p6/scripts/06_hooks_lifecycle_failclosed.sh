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
p6_write_instrumented_cli "$INSTRUMENTED_CLI" "$CALLS"

printf '\n== lifecycle setup ==\n'
init_json="$(p6_cli init)"
printf '%s\n' "$init_json"
p6_assert_ok "$init_json"
ledger_before="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"

first_install="$(p6_cli hook install claude --config "$CONFIG" --cli "$INSTRUMENTED_CLI")"
second_install="$(p6_cli hook install claude --config "$CONFIG" --cli "$INSTRUMENTED_CLI")"
printf '\n== install ==\n%s\n== repeat install ==\n%s\n' "$first_install" "$second_install"
p6_assert_ok "$first_install"
p6_assert_ok "$second_install"
P6_JSON="$second_install" python3 - <<'PY'
import json
import os
if json.loads(os.environ["P6_JSON"])["results"][0].get("changed") is not False:
    raise SystemExit(os.environ["P6_JSON"])
PY

status_installed="$(p6_cli hook status claude)"
printf '\n== installed status ==\n%s\n' "$status_installed"
p6_assert_ok "$status_installed"
P6_JSON="$status_installed" python3 - <<'PY'
import json
import os
result = json.loads(os.environ["P6_JSON"])["results"][0]
if not result.get("installed") or not result.get("enabled") or not result.get("enforced"):
    raise SystemExit(json.dumps(result, sort_keys=True))
PY

disable_json="$(p6_cli hook disable claude)"
disable_again_json="$(p6_cli hook disable claude)"
status_disabled="$(p6_cli hook status claude)"
printf '\n== disable ==\n%s\n== repeat disable ==\n%s\n== disabled status ==\n%s\n' \
    "$disable_json" "$disable_again_json" "$status_disabled"
p6_assert_ok "$disable_json"
p6_assert_ok "$disable_again_json"
p6_assert_ok "$status_disabled"
P6_JSON="$disable_json" P6_AGAIN="$disable_again_json" P6_STATUS="$status_disabled" python3 - <<'PY'
import json
import os
disabled = json.loads(os.environ["P6_JSON"])["results"][0]
again = json.loads(os.environ["P6_AGAIN"])["results"][0]
status = json.loads(os.environ["P6_STATUS"])["results"][0]
if disabled.get("enabled") is not False or not disabled.get("raw_delete_outside_boundary"):
    raise SystemExit(json.dumps(disabled, sort_keys=True))
if again.get("changed") is not False or status.get("enforced") is not False:
    raise SystemExit(json.dumps({"again": again, "status": status}, sort_keys=True))
PY

uninstall_json="$(p6_cli hook uninstall claude)"
uninstall_again_json="$(p6_cli hook uninstall claude)"
printf '\n== uninstall ==\n%s\n== repeat uninstall ==\n%s\n' "$uninstall_json" "$uninstall_again_json"
p6_assert_ok "$uninstall_json"
p6_assert_ok "$uninstall_again_json"
P6_JSON="$uninstall_json" P6_AGAIN="$uninstall_again_json" python3 - <<'PY'
import json
import os
uninstalled = json.loads(os.environ["P6_JSON"])["results"][0]
again = json.loads(os.environ["P6_AGAIN"])["results"][0]
if uninstalled.get("installed") is not False or again.get("changed") is not False:
    raise SystemExit(json.dumps({"uninstalled": uninstalled, "again": again}, sort_keys=True))
PY

ledger_after="$(sha256sum "$SAFE_DELETE_ROOT/ledger.jsonl" | awk '{print $1}')"
printf 'ledger_sha256_before=%s\nledger_sha256_after=%s\nruntime_ledger_unchanged=%s\n' \
    "$ledger_before" "$ledger_after" "$([[ "$ledger_before" == "$ledger_after" ]] && printf true || printf false)"
[[ "$ledger_before" == "$ledger_after" ]]

printf '\n== focused fail-closed and pass-through tests ==\n'
printf '%s\n' 'python3 -m unittest -v tests.test_hook_enforcement.HookEnforcementTests.test_nonzero_cli_is_denied_and_has_no_raw_fallback tests.test_hook_enforcement.HookEnforcementTests.test_installed_route_propagates_real_cli_failure_without_raw_fallback tests.test_hook_enforcement.HookEnforcementTests.test_cross_device_cli_error_is_propagated_without_raw_fallback tests.test_hook_enforcement.HookEnforcementTests.test_unavailable_cli_and_storage_fail_closed_before_child tests.test_hook_enforcement.HookEnforcementTests.test_unregistered_or_disabled_integration_denies_raw_route tests.test_hook_enforcement.HookEnforcementTests.test_malformed_required_context_denies_with_echo_when_possible tests.test_hook_enforcement.HookEnforcementTests.test_unsupported_or_ambiguous_vectors_deny tests.test_hook_enforcement.HookEnforcementTests.test_probes_and_already_safe_delete_pass_through tests.test_hook_enforcement.HookEnforcementTests.test_direct_safe_delete_add_is_passed_through_once tests.test_hook_enforcement.HookEnforcementTests.test_decide_denies_missing_non_directory_and_inaccessible_cwd tests.test_hook_enforcement.HookEnforcementTests.test_unwritable_ledger_fails_closed_without_child'
python3 -m unittest -v \
    tests.test_hook_enforcement.HookEnforcementTests.test_nonzero_cli_is_denied_and_has_no_raw_fallback \
    tests.test_hook_enforcement.HookEnforcementTests.test_installed_route_propagates_real_cli_failure_without_raw_fallback \
    tests.test_hook_enforcement.HookEnforcementTests.test_cross_device_cli_error_is_propagated_without_raw_fallback \
    tests.test_hook_enforcement.HookEnforcementTests.test_unavailable_cli_and_storage_fail_closed_before_child \
    tests.test_hook_enforcement.HookEnforcementTests.test_unregistered_or_disabled_integration_denies_raw_route \
    tests.test_hook_enforcement.HookEnforcementTests.test_malformed_required_context_denies_with_echo_when_possible \
    tests.test_hook_enforcement.HookEnforcementTests.test_unsupported_or_ambiguous_vectors_deny \
    tests.test_hook_enforcement.HookEnforcementTests.test_probes_and_already_safe_delete_pass_through \
    tests.test_hook_enforcement.HookEnforcementTests.test_direct_safe_delete_add_is_passed_through_once \
    tests.test_hook_enforcement.HookEnforcementTests.test_decide_denies_missing_non_directory_and_inaccessible_cwd \
    tests.test_hook_enforcement.HookEnforcementTests.test_unwritable_ledger_fails_closed_without_child

p6_finish_replay
