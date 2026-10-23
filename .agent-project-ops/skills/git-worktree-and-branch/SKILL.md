---
name: git-worktree-and-branch
description: >
  Create and retire git worktrees and origin-only topic branches for Agent-owned
  work. Use when starting a task, running parallel Agents, naming feat/fix/docs/evidence
  branches, after a PR merges or closes (retire its folder and branch), parking or
  abandoning a task, or when tempted to commit on main. Only GitHub origin is supported.
---

# Git worktree and branch

Follow **[PRINCIPLES.md](../../PRINCIPLES.md)** §8 (one task ≈ one branch ≈ one PR; a single task uses the idle primary checkout; finished work is retired automatically, only with proof), §5 fail-closed remotes, and §10 (one write authority).

## Playbooks

- [playbooks/git-worktree.md](../../playbooks/git-worktree.md)
- [playbooks/git-branch-and-remote.md](../../playbooks/git-branch-and-remote.md)
- Helper: [scripts/new-worktree.sh](../../scripts/new-worktree.sh) — start or resume a task (runs tidy first)
- Helper: [scripts/tidy-worktrees.sh](../../scripts/tidy-worktrees.sh) — retire finished work; `--park` / `--abandon`

## Conventions (do not improvise)

| Item | Rule |
| --- | --- |
| Working directory | single task: the idle primary checkout (`mode: here`); parallel tasks: `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}` |
| Folder cap | `max_worktrees` in `.agent-project-ops/project-config` (default 3, `0` = unlimited); exit 3 = queue the task, never bypass |
| Remote | GitHub `origin` only; extra remotes are unsupported and preserved for migration review |
| Branch | `feat\|fix\|docs\|evidence/{issue}-{slug}` |
| Base | approved origin task base: explicit selection, reviewed project config, or verified remote default |
| `main` | never push; the primary checkout carries at most one task branch and returns to the default branch when that task lands |
| Retire | `scripts/tidy-worktrees.sh --apply`: merged PR → delete folder + branches; closed PR → push `archive/<branch>-<sha7>`, then delete; uncommitted, unmerged, open, no-PR or unverifiable → keep and list |
| Evidence | tests and proofs may accompany the task PR or Issue; a separate `evidence/` PR is optional |

## Agent checklist

1. `git remote -v` → only GitHub `origin` is supported. Extra remotes stop affected writes; do not use or silently delete them.
2. Implementation requires a `CONTRACT FREEZE` with a `大改动检查` line and, on a PRINCIPLES §11 hit, the approved start confirmation. Else stop.
3. Determine the task base from the approved Issue/Phase, reviewed `.agent-project-ops/project-config`, or the real GitHub origin default. If ambiguous, offer *verified* `origin/*` candidates via the host's native choice tool (or ordinary conversation); in headless mode require explicit `--base origin/BRANCH`. Use `scripts/new-worktree.sh <issue> <owner> <slug> [kind] [--base origin/BRANCH] [--save-base] [--here|--worktree]`; work where its `workdir:` / `worktree:` line says. Exit 3 = folder cap reached, nothing created: queue the task or park one; do not raise the cap or delete folders by hand.
4. Comment mode + working directory + branch on the Issue.
5. `git push -u origin HEAD`. Open PR to default branch. Never push to a non-origin remote.
6. After merge or close: `scripts/tidy-worktrees.sh --apply` (it also runs before every new task) and quote its `apo-tidy:` line. Pause = commit + push, then `--park <branch>`; abandon (lead Agent's call; the disposer's when dropping the task changes a confirmed goal) = `--abandon <branch>`, which archives before deleting. Never `git worktree remove --force` or `git branch -D` by hand. Next task bases on the new authority tip.

Ignore `.worktrees/` in the **business** repo. Do not vendor this methodology into app packages.
