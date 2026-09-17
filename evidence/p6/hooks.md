# P4 hook evidence status

This page is intentionally a blocker register, not a proof result. All rows
below have status `BLOCKED_PENDING_P4` and result `pending` because the P4
implementation is still proposed in [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18).
The pending tip is `3c05291` / full SHA
`3c052912d3bc7fae84a9258ccae40c56ed32ff40`.

Do not checkout, rebase onto, cherry-pick from, run hook scripts against, or
copy implementation from `feat/6-hook-enforcement`. These rows become replay
targets only after PR #18 lands on `main`, with the landed SHA recorded in a
later capture.

| gate_id | status | pending PR / tip | result | replay target | coverage note |
|---|---|---|---|---|---|
| `P4-pretooluse` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | Supported PreToolUse `rm` vectors and exact one-child invocation | No hook code is present or executed in this scaffold. |
| `P4-path-shim-rm` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | PATH-shim `rm` forms, including frozen `-r`/`-R`/`-f`/`--` cases | No PATH shim is installed or resolved here. |
| `P4-path-shim-unlink-rmdir` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | PATH-shim `unlink` and `rmdir` vectors | No raw deletion command is substituted by this branch. |
| `P4-fail-closed` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | Cross-device, ambiguous, unavailable, unwritable, and nonzero-child cases | Fail-closed proof is pending P4 implementation and capture. |
| `P4-pass-through` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | `rm --help`, `rm --version`, no-operand, and direct CLI probes | Probe behavior must be captured against landed P4 only. |
| `P4-install-lifecycle` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | Install/status/disable/uninstall idempotence and selected boundary | No user config or host registration is changed here. |
| `P6-hook-leg` | `BLOCKED_PENDING_P4` | [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18); `3c05291` / `3c052912d3bc7fae84a9258ccae40c56ed32ff40` | `pending` | Composite hook → CLI → trash/ledger entry | P6 composite remains incomplete and cannot be PASS while this row is pending. |

The direct CLI scripts in this branch are not a substitute for these rows.
