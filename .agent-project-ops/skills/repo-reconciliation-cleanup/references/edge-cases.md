# Edge cases (normative)

### E-DIVERGE — Local ↔ remote fully diverged

Stop bulk deletes until disposer picks:

| Path | When | Steps |
| --- | --- | --- |
| **A Authority wins** | local-only disposable | list SHAs to abandon; explicit auth; hard reset to origin |
| **B Local wins** | remote tip wrong | PR or force-with-lease with explicit auth |
| **C Reclaim both** | both valuable | `reclaim/local-YYYYMMDD` PR into authority, then align local |

Always paste both `origin..HEAD` and `HEAD..origin` logs before asking.

### E-T1 — GitHub + local only

Only origin and local surfaces apply. Additional hosts are unsupported and reported as a stop condition.

### E-T0 — Local only

No remote deletes. Offer add-origin+push as separate auth.

### E-UNREACHABLE

Mark surface UNREACHABLE; clean only reachable; never claim fully clean.

### E-PROD-UNKNOWN / E-PROD-ORPHAN

UNKNOWN: classify vs Dev SoT only. ORPHAN (SHA not in authority history): deploy identity only — never reset authority to it.

### E-AHEAD-UNRELEASED

Authority ahead of PROD = unreleased keep, not dirt.

### E-PROTECTED-DELETE-DENIED

Record failure; do not escalate to admin delete without explicit auth.

### E-WORKTREE-LOCKED

List dirty paths; force-remove only after auth.

### E-DEFAULT-RENAMED

Fix tracking (`master`↔`main`) before classify.

### E-FORK-PR

Cannot delete fork head; close/leave PR; note fork owner.

### E-SUBMODULE-LFS

Treat as unique content in reclaim decision.

### E-SECRETS-IN-UNIQUE

Scan before reclaim merge; prefer abandon+rotate over merging secrets.

### E-MULTI-CLONE

Inventory all clones; do not delete remote branch still checked out elsewhere.

### E-EMPTY-OR-NEW

Skip cleanup; use bootstrap skill instead.
