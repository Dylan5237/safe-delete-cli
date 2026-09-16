# Playbook: Git worktree / 工作树

## Goal

Isolate each in-flight task in its own worktree so Agents do not clobber each other’s index, and so one task maps to one PR branch.

## When

- Starting implementation or evidence work.
- Running a second Agent in parallel.
- Need a clean tree without stashing unrelated work on `main`.

## Preconditions

- Business repo clone exists; `origin` is configured (`playbooks/git-branch-and-remote.md`). If a projection remote exists, also load `playbooks/git-authority-and-projection.md`.
- Target Issue exists; Phase is Freeze-ACK’d if this is implementation.
- `.worktrees/` is gitignored in the business repo (add it if missing). Do **not** commit worktree contents as a nested repo.

## Steps

1. **Name the slot.** `{issue-or-phase}-{owner}-{slug}`
   - `issue-or-phase`: `p12` or `123` (issue number) or `p12-t3` for a child task.
   - `owner`: short agent or handle slug (`agent`, `dylan`).
   - `slug`: kebab-case, ≤ 40 chars, from the issue title.
2. **Path:** `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`  
   Example: `~/src/app/.worktrees/42-agent-add-healthcheck`
3. **Base = current authority tip.** Fetch `origin`. Create the worktree from the tip Command Center treats as SoT — usually `origin/main`, or a **named transitional branch** until that branch merges to the default branch. Do not start from a stale local `main` or from projection.
4. **Create** (helper): from the **primary clone** (keep that checkout on the default branch and **clean**, for fetch/sync only — no long-lived feature work there),

   ```bash
   # optional
   scripts/new-worktree.sh 42 agent add-healthcheck feat
   # or:
   git fetch origin
   git worktree add -b feat/42-add-healthcheck .worktrees/42-agent-add-healthcheck origin/main
   # if Command Center names a transitional tip instead of main:
   # git worktree add -b feat/42-add-healthcheck .worktrees/42-agent-add-healthcheck origin/<authority-tip-branch>
   ```

5. **Bind.** Comment on the Issue: worktree absolute/relative path, branch name, HEAD sha after create.
6. **Work only in that directory.** `cd` into the worktree for commits and `git push -u origin <branch>` (never to a projection remote).
7. **End of task:** after PR merge or abandon:

   ```bash
   git worktree remove .worktrees/42-agent-add-healthcheck
   # if dirty and abandoned: commit or discard explicitly, then remove
   ```

8. **List:** `git worktree list` — every extra path should match an `in-progress` or `verification` issue. The primary path should remain a clean sync checkout, not a second feature tree.

## Done when

- [ ] Path matches `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`.
- [ ] Branch in that worktree is the PR branch (not `main`); it was created from the current authority tip.
- [ ] Primary clone is not the long-lived feature checkout.
- [ ] Issue comment records the path.
- [ ] Removed or parked when the PR is done.

## Anti-patterns

- Extra clones in random directories instead of `.worktrees/`.
- Using the primary `main` checkout for a long-lived feature (it stays clean for sync).
- Basing a worktree on projection or on a superseded transitional branch after the authority tip has merged.
- Two issues, one worktree.
- Committing `.worktrees/` into git.
- Creating a worktree before Freeze on an implementation task.
