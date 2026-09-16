# Playbook: Git authority and projection / 权威远端与投影远端

## Goal

When a project **optionally** has a second git remote, keep **exactly one write authority**. The second remote is a **projection** (mirror / fast-forward from authority). Local clones and Cloud Agent sandboxes are **drafts**, never a third source of truth.

Single-remote projects skip this playbook and stay on [git-branch-and-remote.md](./git-branch-and-remote.md) (`origin` only).

## When

- `git remote -v` shows more than `origin`.
- Command Center names a projection host (for example an internal GitLab) in addition to GitHub.
- Before any non-`origin` push, release cut, history rewrite on a protected default branch, or branch cleanup across remotes.
- Tips disagree: projection SHA is not an ancestor of (or identical to) the authority tip.

## Preconditions

- Command Center records: **authority remote + default branch**, optional **projection remote name**, and the **disposer** who may authorize force or abandon.
- Authority is the GitHub repository used for Issues/PRs (control plane). Projection has **no** day-to-day Issues workflow in this methodology.
- Agents (local or Cloud) have the same push rights as humans: **no** privileged push to protected `main`.
- [PRINCIPLES.md](../PRINCIPLES.md) §5 (fail closed) and §10 (one write authority) are in force.

## Terms

| Term | Meaning |
| --- | --- |
| **Authority** | The GitHub repo/remote (usually `origin`) whose named branch tip is source of truth for history that Issues and PRs describe. |
| **Authority tip** | The commit Command Center currently treats as the integration head: usually `origin/main`, or a **named transitional branch** until it merges to the default branch. |
| **Projection** | A second remote used only to **mirror** authority (fetch + fast-forward, or disposer-authorized align). Never a feature-push target. |
| **Local / Cloud checkout** | Draft. Commits exist for the rest of the project only after they land on **authority** via PR. |
| **Aux / skill repo** | A separate methodology or helper repository, if the business clone is not the only git surface. Read-only in reconciliation; do not treat it as product SoT. |

Suggested remote name for the second URL: `projection` (not `origin`, not `upstream` used as a shadow write path).

## Steps

### A. Classify remotes / 先分类

1. `git remote -v`. Label each URL as **authority**, **projection**, or **unknown**.
2. Unknown extra remotes → `status:blocked` on Command Center or the active Issue until the disposer names them. Do **not** push “to be safe” to every URL.
3. Topic branches (`feat/` `fix/` `docs/` `evidence/` and Agent-private `cursor/` / `sync/` drafts) push **only** to authority `origin`:

   ```bash
   git push -u origin HEAD
   ```

   Never: `git push projection HEAD` for a feature or evidence branch.

### B. Day-to-day landing / 日常落地

1. Fetch authority; start work from the **current authority tip** ([git-worktree.md](./git-worktree.md)).
2. Open PRs **on authority** targeting the default branch (or the Command Center–named transitional branch).
3. After the authority tip **merges** to the default branch, new work starts from that new tip. Do not keep basing on a superseded transitional branch.
4. **Cloud Agents** follow the same rules as humans: no privileged push to `main`, no topic pushes to projection. A Cloud sandbox is still local draft.
5. Projection is updated **only** as a mirror step after authority history is the intended one (fast-forward preferred).

### C. Project the mirror / 投影（快进优先）

1. Fetch both remotes. Confirm the projection default branch is a fast-forward of the authority tip, or equal.
2. If equal or behind: fast-forward the projection default branch from the authority tip. Record both SHAs on the Issue.
3. If projection **cannot** be updated (auth, network, protection, hook): **fail closed**. Do not ship or announce a release that assumed the projection exists. Comment `BLOCKED:` with the gap. Projection failure **stops release**, it does not justify pushing features to projection or rewriting authority to match a stale mirror.
4. Do not use projection as a workaround when `origin` or protected `main` rules are unreachable (Principle 5).

### D. Divergence: projection ahead of authority / 投影超前

If projection’s default branch contains commits **not** on the authority tip:

1. Label the work **Blocked**. Stop projecting and stop treating projection as “already shipped.”
2. Choose **one** disposer-written path **before** any further projection:
   - **Backfill:** recreate the unique work as a PR **on authority** (cherry-pick or equivalent onto the authority tip). Merge on GitHub. Then align projection to authority (see §E). Recreated commits have new SHAs, so projection is not an ancestor of the new authority tip and fast-forward will usually fail.
   - **Abandon:** disposer comments that the unique projection commits are discarded; then align projection to authority (see §E). Unique work that was only on projection is gone unless backfilled first.
3. Inventing a second SoT (“GitLab is production now”) is forbidden.

### E. Aligning protected `main` / 对齐受保护默认分支

When unique commits exist on a diverged default branch (usually projection `main` vs authority `main`):

1. **Reclaim first.** Cherry-pick or re-PR any **useful** unique commits onto the **current authority tip**. Land them through the normal PR path. Do not skip this because a force would be shorter.
2. **Then** align the diverged branch to that tip:
   - Prefer **fast-forward**.
   - **Force** (or force-with-lease) on a default branch **only** with **explicit disposer authorization** on the Issue (who, when, from-SHA, to-SHA, why reclaim is complete).
3. If branch protection **blocks** force: **merge-align** (merge the authority tip into the diverged default, or the reverse **only** as the disposer specifies) so both sides share a recorded merge commit. Write both resulting tips on the Issue. Do not loop force attempts.
4. Agents never self-authorize force on `main`. Cloud Agents have no extra privilege.

### F. Read-only three-surface reconciliation / 清理前只读对账

**Before** deleting branches or declaring remotes “in sync,” fill a table on the Issue (fetch all; **no** push in this step):

| Surface | Remote / repo | Default-branch SHA | Authority tip SHA (if different) | Unique commits vs authority tip | In-flight PRs / topic branches | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Authority | `origin` (GitHub) | | | (should be none vs itself) | | SoT |
| Projection | e.g. `projection` | | | ahead / behind / diverge / equal | should be none for features | mirror only |
| Aux / skill (if any) | third clone or methodology repo | | | n/a or docs-only | | not product SoT |

- If there is no aux repo, write `n/a` — do not invent a third product remote.
- “Reconciled” means: projection default is FF-or-equal to authority tip (or disposer-recorded merge-align), and local/Cloud drafts are pushed to authority or explicitly abandoned.
- Merge on authority **still** is not Phase PASS ([PRINCIPLES.md](../PRINCIPLES.md) §3).

### G. Cleanup red lines / 清理红线

After §F is on the Issue and the disposer has authorized cleanup:

| Class | Examples | Rule |
| --- | --- | --- |
| **Never delete** | Current **authority tip** branch; open or landed **evidence** PRs and `evidence/*` branches still referenced by a Phase; **merged implementation** history needed to explain `main` | Leave them. Closing a PR ≠ deleting the evidence trail. |
| **Low-risk stale** | Agent-private `cursor/*`, `sync/*` (or equivalent) with **no** open PR, **no** unique commits vs already-merged work | Delete **only after disposer auth**, after §F shows they are stale on **authority**. Do not delete their last copy if it never reached `origin`. |
| **High-risk / separate decision** | **Diverged `main`** on any remote; **docs** (or other) PRs **targeting an old main / old tip** | Do not delete or retarget as part of “hygiene.” Open a dedicated Issue or Exception; disposer chooses reclaim, retarget, or close. |

Never delete a branch solely because it exists on projection; projection should not have unique topic branches. If it does, treat as divergence (§D), not as junk.

## Done when

- [ ] Command Center names authority vs projection (or states origin-only and this playbook does not apply).
- [ ] Topic branches exist on `origin` only; projection default is FF/equal or a disposer-recorded align.
- [ ] Cloud and local Agents pushed features only via PRs to authority; never to `main`, never to projection as a workflow.
- [ ] If tips had diverged: backfill or written abandon happened **before** projecting.
- [ ] Reconciliation table posted before any cleanup; red lines respected.

## Anti-patterns

- Day-to-day `git push` of `feat/` / `fix/` / `docs/` / `evidence/` to the projection remote.
- Treating local `main` or a Cloud checkout as caught-up SoT without fetching authority.
- Using projection because GitHub `origin` was down (second SoT / Principle 5).
- Force-pushing protected `main` without disposer SHAs on the Issue.
- Deleting `evidence/*`, the authority tip, or PRs aimed at an old `main` during “cleanup.”
- Skipping projection update and still calling a release done when Command Center requires the mirror.
- Granting Cloud Agents a bypass of branch protection.
