# Playbook: Git worktree / 工作树

## Goal

One task = one branch = one PR, and Agents never share an index. A single task runs on the **idle primary checkout** (no extra folder); only parallel tasks get their own worktree under `.worktrees/`, capped by `max_worktrees`. Finished folders and branches are retired automatically by `scripts/tidy-worktrees.sh`, but only with proof that nothing is lost.

## When

- Starting implementation or evidence work.
- Running a second Agent in parallel.
- After a PR merges or closes, before a status report, and before proposing Phase acceptance (tidy).
- Pausing (parking) or abandoning a task.

## Preconditions

- Business repo clone exists; only GitHub `origin` is supported (`playbooks/git-branch-and-remote.md`). Additional remotes must be reviewed separately, never used as task bases or write targets.
- Target Issue exists; for implementation, its contract is frozen (and start-confirmed if it hit the PRINCIPLES §11 list).
- `.worktrees/` is gitignored in the business repo (add it if missing). Do **not** commit worktree contents as a nested repo.
- `gh` authenticated for the GitHub origin (recommended). Without it, tidy retires only branches whose `origin/<branch>` was deleted after landing in the default branch, and keeps everything else.

## Steps

1. **Name the slot.** `{issue-or-phase}-{owner}-{slug}`
   - `issue-or-phase`: `p12` or `123` (issue number) or `p12-t3` for a child task.
   - `owner`: short agent or handle slug (`agent`, `dylan`).
   - `slug`: kebab-case, ≤ 40 chars, from the issue title.
2. **Path** (only when the task needs its own folder): `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`  
   Example: `~/src/app/.worktrees/42-agent-add-healthcheck`
3. **Base = approved task origin ref.** Fetch `origin`. Resolve an explicit `--base`, otherwise the reviewed `.agent-project-ops/project-config` (`task_base=origin/BRANCH`), otherwise GitHub origin's verified remote default. A task may use `origin/develop` without changing the repository's default branch or write authority. If ambiguous, stop and ask rather than guessing `origin/main`.
4. **Create** (helper; run from any checkout of the repo — it anchors on the primary checkout):

   ```bash
   # Auto-detect reviewed project base or verified remote default:
   scripts/new-worktree.sh 42 agent add-healthcheck feat
   # For an explicitly chosen development base:
   scripts/new-worktree.sh 43 agent another-task feat --base origin/develop
   # Record that choice as this project's new default on the *task branch*:
   scripts/new-worktree.sh 44 agent third-task feat --base origin/develop --save-base
   # Force a separate folder even though the primary checkout is idle:
   scripts/new-worktree.sh 45 agent parallel-task feat --worktree
   ```

   What it does, in order:
   - `git fetch --prune origin`, then `tidy-worktrees.sh --apply --quiet --no-fetch` retires finished work first. Tidy problems are warnings, never blockers.
   - **`mode: here`** — the primary checkout is idle (not on a `feat|fix|docs|evidence/` branch, no changes): the task branch is created right there. A single task needs no extra folder. `--here` insists on this and fails if the primary checkout is busy.
   - **`mode: worktree`** — the primary checkout is busy, or `--worktree`, or `worktree_mode=always`: the task gets `{repo}/.worktrees/{slot}`.
   - **Folder cap.** Folders under `.worktrees/` are capped by `max_worktrees`. At the cap the helper exits **3** and creates nothing: finish, merge or park a task, or queue this one. Never raise the cap or delete another task's folder to get past it.
   - **Resume.** If the branch already exists locally or as `origin/<branch>`, it is resumed instead of recreated (this is how a parked task comes back). `--base` / `--save-base` are refused for an existing branch.

   Project settings live in `.agent-project-ops/project-config` (one `key=value` per line, reviewed through a PR; unknown keys are refused, never executed):

   | Key | Default | Meaning |
   | --- | --- | --- |
   | `task_base=origin/BRANCH` | verified remote default | base for new task branches |
   | `max_worktrees=N` | `3` | cap on folders under `.worktrees/`; `0` = unlimited |
   | `worktree_mode=auto\|always` | `auto` | `always` = never put a task on the primary checkout |
   | `process_mode=light\|standard` | `standard` | process mode (PRINCIPLES §0), chosen by the disposer; the helper only validates it |
   | agent_tools=comma-separated IDs | required at new initialization | nonempty selection from templates/project-options.json; validated together with the other initialization choices |
   | external_tools=none or comma-separated IDs | none when explicitly chosen | optional instructions only; validated together with process_mode and agent_tools |

5. **Bind.** Comment on the Issue: `mode`, working directory (the `workdir:` or `worktree:` line), branch, selected origin base, its source, and HEAD SHA. With `--save-base`, review/commit the generated `.agent-project-ops/project-config` through the task PR. In `worktree` mode the primary checkout must remain unchanged.
6. **Work only in that directory.** `cd` into it for commits and `git push -u origin <branch>` (never to another remote).
7. **Retire (automatic, evidence-based).** `scripts/tidy-worktrees.sh` decides per folder and branch:

   | Situation | With `--apply` |
   | --- | --- |
   | PR **merged** (squash/rebase included: the PR head equals or contains the local tip), no uncommitted or ignored files, no commits after the merged head | remove the folder, delete the local and `origin` branch; a primary checkout on that branch switches back to the default branch and fast-forwards |
   | PR **closed unmerged**, clean | push tag `archive/<branch>-<sha7>` to origin first, then remove folder and branches |
   | Uncommitted or ignored files, commits after the merge, PR open, no PR yet, locked, detached, outside `.worktrees/` (other tools), the folder you are standing in, or anything it cannot verify | **keep** and list the reason; `stale` after `--stale-days` (default 7) |
   | Default branch, `task_base`, `main` `master` `develop` `dev` `trunk` `staging` `production` `prod` `gh-pages`, `release*`, `hotfix/*` | never touched |

   It runs before every new task (step 4). Agents also run it after a PR merges or closes, before each status report, and before proposing Phase acceptance:

   ```bash
   scripts/tidy-worktrees.sh            # read-only plan (default)
   scripts/tidy-worktrees.sh --apply    # act on proven cases only
   ```

   Ignored files (including caches and local configuration) also prevent automatic removal, parking, abandoning, or switching the primary checkout. Archive tags preserve commits only, not these files. Only the primary checkout's root `.worktrees/` is excluded from its status check; each task folder is checked separately. Any later disposal of ignored contents needs its own approved inventory.

   The last line is a fixed summary; paste it into status reports and acceptance proposals:

   ```text
   apo-tidy: mode=apply gh=ok fetch=ok folders_removed=1 branches_deleted=1 remote_deleted=1 archived=0 kept=2 stale=0 failed=0 folders_left=1/3
   ```

   Counters describe completed actions. In `mode=report`, `folders_removed`, `branches_deleted`, `remote_deleted`, and `archived` are all zero; `folders_left` counts existing directories directly under the primary `.worktrees/`, including hidden or unregistered folders. Planned actions appear in `plan` lines. Reporting still refreshes local remote-tracking refs and may fetch missing PR head objects; it does not delete task folders or branches.

   Exit `1` = an action failed or was refused (for example a folder still open in an editor on Windows); nothing is lost and the next run retries. Exit `2` = usage error. Branches created by other tools outside `.worktrees/` are only listed; `--include-other` lets tidy consider them under the same proof rules.

   **Pause or abandon:**

   ```bash
   # Park (pause): commit and push everything first; the branch stays, the folder goes
   # (a primary checkout switches back to the default branch instead).
   git -C .worktrees/42-agent-add-healthcheck push -u origin HEAD
   scripts/tidy-worktrees.sh --park feat/42-add-healthcheck
   # Resume later: new-worktree.sh with the same issue, owner, slug and kind.

   # Abandon (lead Agent's call; the disposer's if dropping it changes a confirmed goal; close the PR first if one is open):
   scripts/tidy-worktrees.sh --abandon feat/42-add-healthcheck
   # pushes archive/<branch>-<sha7>, then removes the folder, local and origin branch
   ```

   Archive tags keep every abandoned or closed tip: restore with `git switch -c <branch> archive/<branch>-<sha7>`. Deleting a branch after its archive tag is pushed is **not** "deleting unmerged work". If a workflow triggers on every tag (`tags: ['**']` or `'*'`), exclude `archive/**` so archiving never starts a release.

8. **List:** `git worktree list` — every extra path should match an `in-progress` or `verification` issue; anything else appears as `keep` in the tidy plan with its reason. The primary checkout is either idle on the default branch or carrying exactly one task branch.

## Done when

- [ ] Single task: on the idle primary checkout (`mode: here`). Parallel tasks: path matches `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`, never more than `max_worktrees` folders.
- [ ] Branch is the PR branch, created from the verified origin base approved for this task.
- [ ] Issue comment records the mode, working directory and branch.
- [ ] After merge or close, `tidy-worktrees.sh --apply` retired it: the `apo-tidy:` line shows `failed=0`, and every `keep` line is a live task or a listed exception.

## Anti-patterns

- Extra clones in random directories instead of `.worktrees/`.
- Two tasks on the primary checkout at once, or leaving it on a finished task branch (tidy switches it back; do not fight it).
- Creating a folder for a single task while the primary checkout is idle (unless `worktree_mode=always`).
- Deleting folders or branches by hand (`git worktree remove --force`, `git branch -D`, `git push --delete`) — use tidy, which proves the work landed or archives it first.
- Raising `max_worktrees` or removing another task's folder to get past exit 3.
- Parking with `git stash` or with unpushed commits (`--park` refuses both).
- Basing a worktree on another remote or on a superseded transitional branch after the authority tip has merged.
- Two issues, one worktree.
- Committing `.worktrees/` into git.
- Creating a worktree before Freeze on an implementation task.
- Assuming `origin/main` despite contrary project state, or silently saving a task override as a project default.
