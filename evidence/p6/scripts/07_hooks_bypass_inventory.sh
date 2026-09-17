#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=00_env.sh
source "$SCRIPT_DIR/00_env.sh"

p6_enter_checkout
p6_require_clean
p6_record_env

printf '\n== frozen bypass inventory ==\n'
python3 - <<'PY'
from safe_delete.hook import OUT_OF_COVERAGE_BYPASSES

for item in OUT_OF_COVERAGE_BYPASSES:
    print(f"out_of_coverage={item}")
PY

printf '\n== representative bypass replay ==\n'
printf '%s\n' 'python3 -m unittest -v tests.test_hook_enforcement.HookEnforcementTests.test_bypass_replay_is_documented_as_out_of_coverage tests.test_hook_enforcement.HookEnforcementTests.test_bypass_replay_executes_representative_out_of_coverage_commands tests.test_hook_enforcement.HookEnforcementTests.test_bypass_inventory_is_reported_as_out_of_coverage'
python3 -m unittest -v \
    tests.test_hook_enforcement.HookEnforcementTests.test_bypass_replay_is_documented_as_out_of_coverage \
    tests.test_hook_enforcement.HookEnforcementTests.test_bypass_replay_executes_representative_out_of_coverage_commands \
    tests.test_hook_enforcement.HookEnforcementTests.test_bypass_inventory_is_reported_as_out_of_coverage

printf 'classification=expected_direct_deletion_without_hook; not a supported-hook failure\n'
p6_finish_replay
