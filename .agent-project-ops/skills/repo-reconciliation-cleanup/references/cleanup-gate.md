# Two-phase cleanup gate (from neat-freak)

Destructive cleanup (delete branches/worktrees/PRs, hard reset) **destroys evidence**. Order is fixed:

1. Inventory + classify (read-only)
2. Resolve E-DIVERGE if present (path chosen, not yet executed if destructive)
3. Fill disposer batch; get explicit auth for the **named** objects
4. Produce **Phase-A report** with full candidate list while evidence still exists
5. Stop — wait for disposer confirmation **after** they saw the report
6. Execute only confirmed objects; count 拦截 / 失败 / 成功
7. Re-run inventory audit; append **Phase-B cleanup result**

### Hard rules

- “做完后清理 / 今天清干净” in the **opening** ask is **not** the Phase-A→B confirmation.
- Exception: disposer answers a widget that lists the exact delete set — that counts as post-preview auth for that set only.
- Never delete the only copy of unique unreclaimed commits.
- Directory age, agent session closed, or branch name patterns alone never prove deletable.

### Light vs full path

| Path | When | Steps |
| --- | --- | --- |
| **Light** | T0/T1, no PROD floor required, few refs, no E-DIVERGE | inventory → classify → one widget with candidates → execute → short report |
| **Full** | E-DIVERGE, release/PROD involved, many diverged, workspace-wide | all phases + fact-surface statuses + two-phase report |

Unsure → full.

T2/T4 unsupported remote settings stop affected cleanup before either path. Preserve them for explicit project migration review.
