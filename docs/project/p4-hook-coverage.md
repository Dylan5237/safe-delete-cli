# P4 hook coverage replay

The P4 hook boundary is intentionally client-side and finite. The replay in
`tests/test_hook_enforcement.py` records bypasses as out of coverage; these are
not failed interception cases and must not be reported as universal-enforcement
failures.

| Vector | Replay result | Classification |
| --- | --- | --- |
| Python/Go/Node filesystem APIs | Not intercepted; adapter denies the opaque argv | Out of coverage |
| `find -delete` | Not intercepted; adapter denies the unsupported executable | Out of coverage |
| `git clean` | Not intercepted; adapter denies the unsupported executable | Out of coverage |
| `busybox rm` | Not intercepted; adapter denies the wrapper | Out of coverage |
| Absolute `/bin/rm`, `/bin/unlink`, `/bin/rmdir` | Not intercepted; adapter denies the non-normalized executable | Out of coverage |
| Another unconfigured agent/tool | Not intercepted; adapter denies the unsupported executable | Out of coverage |
| Container/namespace without the hook, privileged or human process | No adapter boundary is present | Out of coverage |
| PATH reordering, disabled or uninstalled integration | Enforcement boundary is intentionally inactive | Out of coverage |

The covered vectors and failure paths remain the acceptance tests in
`tests/test_hook_enforcement.py`; the bypass replay only documents the frozen
limits.
