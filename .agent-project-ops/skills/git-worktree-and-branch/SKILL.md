---
name: git-worktree-and-branch
description: >
  Create and retire git worktrees and origin-only topic branches for Agent-owned
  work. Use when starting a task, running parallel Agents, naming feat/fix/docs/evidence
  branches, or when tempted to commit on main. Also use when a second remote,
  projection/mirror, multi-remote setup, or authority-vs-projection tip
  reconciliation appears — then load git-authority-and-projection before any
  non-origin push.
---

# Git worktree and branch

Follow **[PRINCIPLES.md](../../PRINCIPLES.md)** §8 (one worktree ≈ one task ≈ one PR branch), §5 fail-closed remotes, and §10 (one write authority).

## Playbooks

- [playbooks/git-worktree.md](../../playbooks/git-worktree.md)
- [playbooks/git-branch-and-remote.md](../../playbooks/git-branch-and-remote.md)
- [playbooks/git-authority-and-projection.md](../../playbooks/git-authority-and-projection.md) — when a projection/second remote exists
- Companion skill: [git-authority-and-projection](../git-authority-and-projection/SKILL.md)
- Helper: [scripts/new-worktree.sh](../../scripts/new-worktree.sh) (optional)

## Conventions (do not improvise)

| Item | Rule |
| --- | --- |
| Worktree path | `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}` |
| Remote | `origin` only for topic pushes; extra remotes are projection, not a second SoT |
| Branch | `feat\|fix\|docs\|evidence/{issue}-{slug}` |
| Base | current **authority tip** (usually `origin/main`) |
| `main` | never push; never use as a long-lived task checkout |
| Evidence vs impl | `evidence/` branches contain no feature diff |

## Agent checklist

1. `git remote -v` → expect `origin` for this workflow. If a **projection** (or any non-origin) remote is configured, follow [git-authority-and-projection](../git-authority-and-projection/SKILL.md) and its playbook **before any non-origin push**.
2. Implementation requires Phase **Freeze ACK**. Else stop.
3. Add worktree from the **current authority tip** (usually `origin/main`, or the Command Center–named transitional branch), not from a dirty unrelated branch. Keep the primary checkout clean for sync.
4. Comment path + branch on the Issue.
5. `git push -u origin HEAD`. Open PR to default branch. Never push topic branches to projection.
6. After merge/abandon: `git worktree remove …` and delete remote topic branch on authority. Next task bases on the new authority tip.

Ignore `.worktrees/` in the **business** repo. Do not vendor this methodology into app packages.
