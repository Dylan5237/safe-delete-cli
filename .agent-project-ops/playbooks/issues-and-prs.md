# Playbook: Issues and PRs / 议题与拉取请求

## Goal

Keep **Issues as state** and **PRs as proposals**. Labels make the board machine-readable for Agents.

## When

- Opening, updating, or closing work.
- Connecting a branch to the control plane.
- Changing status.

## Preconditions

- Command Center exists.
- Labels from `templates/labels.md` are applied on the business repo.
- Chat decisions will be copied into the Issue in the same session.

## Steps

1. **Choose the issue type**
   - Command Center: one per repo (index, roster, policy).
   - Phase: one core problem; lifecycle in `phase-lifecycle.md`.
   - Child task (optional): small implementable slice under a Phase; still one PR.
   - Architecture Exception: frozen-contract change request.
2. **Status label (exactly one):**
   - `status:backlog` — not started
   - `status:in-progress` — dispatched, worktree exists
   - `status:blocked` — cannot proceed; gap listed
   - `status:verification` — implementation proposed; evidence in flight or waiting Accept
   - `status:done` — disposer finished (Accept or explicit cancel)
3. **Type labels:** `type:command-center` | `type:phase` | `type:task` | `type:exception` | `type:docs`
4. **Open implementation PR** with `templates/PULL_REQUEST_TEMPLATE/implementation.md`.
   - Title: `{type}(#{issue}): short slug`
   - Body: links Issue, Freeze permalink, test plan, NON-GOALS respected.
   - Label PR `pr:implementation`. Do not add product-only labels from a business SOP pack.
5. **Open evidence PR** (if artifacts are in git) with `templates/PULL_REQUEST_TEMPLATE/evidence.md`, label `pr:evidence`, branch `evidence/{issue}-{slug}`.
6. **Comments are the log.** Status changes get a one-line reason. Paste command output **summaries** that matter; do not dump secrets.
7. **Close rules.** Close tasks when their PR is merged **and** the Phase still owns Accept. Close Phase only after `PHASE ACCEPT` or documented supersede. Closing a PR ≠ closing a Phase.

## Done when

- [ ] Every in-flight branch has a linked open Issue.
- [ ] Exactly one `status:*` label on each tracked Issue.
- [ ] PRs declare implementation vs evidence.
- [ ] Command Center table lists open Phases.

## Anti-patterns

- Issues with empty bodies (“fix it”).
- Five status labels at once.
- PR with no linked Issue.
- Using Projects/boards as the only state and leaving Issues blank.
- Merging then deleting the Issue before Accept is recorded.
