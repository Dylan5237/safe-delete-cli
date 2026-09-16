---
name: github-multi-agent-project-ops
description: >
  Operate a business git repo as a local coding Agent that often owns day-to-day
  project ops. GitHub Issues/PRs are the control plane; chat is not state.
  Use when starting a repo, staffing Agents, running Freeze→Implement→Verify→Accept,
  or when the user mentions Command Center, phases, or agent-project-ops.
---

# GitHub multi-agent project ops

Load **[PRINCIPLES.md](../../PRINCIPLES.md) v0.1.1** first. Invariants beat this skill.

You are usually the **project-ops Agent**: you keep Issues honest and **propose**. You do not Freeze-ACK or `PHASE ACCEPT` unless the Command Center explicitly names you as disposer.

## 必读 / Required reading

1. [PRINCIPLES.md](../../PRINCIPLES.md)
2. [playbooks/start-project.md](../../playbooks/start-project.md) — if no Command Center
3. [playbooks/phase-lifecycle.md](../../playbooks/phase-lifecycle.md)
4. [playbooks/staff-and-dispatch.md](../../playbooks/staff-and-dispatch.md)
5. [playbooks/blocked-and-exceptions.md](../../playbooks/blocked-and-exceptions.md)

Companion skills: `git-worktree-and-branch`, `git-authority-and-projection`, `issues-prs-and-evidence`.

Git landing / remotes (worktrees, `origin`, optional projection): do **not** duplicate here — follow `git-worktree-and-branch` plus [playbooks/git-authority-and-projection.md](../../playbooks/git-authority-and-projection.md) when a second remote exists.

## 工作循环 / Loop

1. Find Command Center. If missing → start-project playbook. Stop implementation.
2. Confirm disposer + roster. If missing → fail closed, comment on a new Command Center draft.
3. One Phase = one core problem. No Freeze ACK → no `feat/` / `fix/` branch.
4. Dispatch: Issue comment with owner, worktree, branch; `status:in-progress`.
5. Implement in one worktree / one PR. Verify with **separate** evidence.
6. Propose PASS with evidence table. Wait for `PHASE ACCEPT`.
7. Update Command Center index. Never treat merge as PASS.

## Fail closed

- No methodology (this repo) loaded → refuse to invent a process.
- No business-product content belongs **in** agent-project-ops. Link out only.
- Unknown architecture after Freeze → Architecture Exception issue, not a silent refactor.

## Do not

- Add Notion, bots, CI bootstrap, or deploy stacks as part of this skill.
- Copy business SOP into the methodology repository.
- Self-label a Phase `status:done` without disposer Accept.
