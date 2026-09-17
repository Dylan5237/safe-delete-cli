# P4 hook coverage replay

This document is the replay map for the frozen P4 gate. It is intentionally
specific about the finite client-side boundary: a bypass is an expected
out-of-coverage result, not a universal-enforcement failure.

## Replay record

Run from the repository checkout (the worktree path may differ for a
disposer):

```text
SHA:       git rev-parse HEAD (the final verification comment records the value)
CWD:       pwd
Command:   python3 -m unittest discover -s tests -v
Environment: Python 3; isolated TemporaryDirectory roots; SAFE_DELETE_ROOT set
             per test; no production paths or credentials
Result:    PASS (94 tests in this fix cycle); the Issue/PR verification comment
           records the resolved SHA and command output summary
```

The focused replay is:

```text
python3 -m unittest tests.test_hook_enforcement -v
```

Each real route test installs a fresh boundary and uses an instrumented real
`safe-delete` CLI. The wrapper appends one line per child invocation. Separate
`rm`/`unlink`/`rmdir` sentinels append to a raw-command marker and exit 97;
an empty marker proves that no raw fallback ran.

## Covered route and failure matrix

| Gate | Boundary and command/test | CWD | Expected result |
| --- | --- | --- | --- |
| B5 | `python3 -m unittest tests.test_hook_enforcement.HookEnforcementTests.test_registered_cli_ignores_safe_delete_cli_override -v` | repository checkout; test creates isolated workspace | Registered CLI runs once; fake `SAFE_DELETE_CLI` is not called; target is moved and exactly one ledger event is written |
| P4 route | `python3 -m unittest tests.test_hook_enforcement.HookEnforcementTests.test_installed_pretooluse_routes_real_vectors_once_without_raw_fallback -v` | isolated `workspace` request cwd | `rm -rf --`, `unlink --`, and `rmdir --` each route once; 3 child calls, 3 ledger events, no raw marker |
| P4 route | `python3 -m unittest tests.test_hook_enforcement.HookEnforcementTests.test_installed_path_routes_real_vectors_once_without_raw_fallback -v` | isolated `workspace` process cwd | PATH `rm -R -f --`, `unlink --`, and `rmdir --` each route once; 3 child calls, 3 ledger events, no raw marker |
| P4 failure | `python3 -m unittest tests.test_hook_enforcement.HookEnforcementTests.test_installed_route_propagates_real_cli_failure_without_raw_fallback -v` | isolated `workspace` request cwd | Real CLI returns `source_not_found`/exit 2 once; no ledger event and no raw marker |
| P4 lifecycle | `python3 -m unittest tests.test_hook_enforcement.HookEnforcementTests.test_install_status_disable_uninstall_are_idempotent_and_scoped -v` | isolated package/config/storage roots | Install/status/disable/uninstall remain scoped and idempotent; runtime ledger bytes are unchanged |

The complete test names above live in `tests/test_hook_enforcement.py`; the
full-suite command is the authoritative result for the tip under review.

## Explicit bypass inventory

The following replay runs commands in isolated temporary directories and
records `(command, cwd, result)` in
`HookEnforcementTests.test_bypass_replay_executes_representative_out_of_coverage_commands`.
They deliberately demonstrate raw deletion with no ledger event; they are not
P4 failures because no supported hook boundary is present or selected.

| Command | CWD | Result / classification |
| --- | --- | --- |
| `python3 -c "import os; os.unlink('api-target')"` | isolated workspace | Target removed directly; no ledger event; API out of coverage |
| `find . -maxdepth 1 -name find-target -delete` | isolated workspace | Target removed directly; no ledger event; `find -delete` out of coverage |
| `git clean -fdq` | isolated temporary Git workspace | Untracked target removed directly; no ledger event; `git clean` out of coverage |
| `/bin/rm absolute-target` | isolated workspace | Target removed directly; no ledger event; absolute binary out of coverage |
| `PATH=raw-dir:shim-dir rm path-reordered-target` | isolated workspace | Raw sentinel runs and target is removed; no ledger event; PATH reordering out of coverage |
| `PATH=os.defpath rm removed-shim-target` | isolated workspace | System `rm` runs after shim removal; no ledger event; removed shim out of coverage |
| Python/Go/Node filesystem APIs, `busybox rm`, another unconfigured agent/tool, container/namespace without hook, privileged or human process | n/a or caller-owned | No supported adapter boundary; out of coverage |

The focused bypass test also retains the adapter-level denial assertions for
opaque vectors. Neither those denials nor the direct replay rows should be
described as proof of interception outside the configured PreToolUse and PATH
boundaries.
