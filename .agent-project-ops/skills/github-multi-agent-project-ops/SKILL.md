---
name: github-multi-agent-project-ops
description: >
  Lead APO project operations: freeze scope, prepare and dispatch task Issues,
  reconcile ownership, review and merge task PRs after required checks, and
  coordinate human final acceptance. Use for Command Center or Phase ownership;
  an Agent assigned only one execution task uses the executor skill instead.
---

# GitHub multi-agent project ops

Load **[PRINCIPLES.md](../../PRINCIPLES.md) v0.3.0** first. Invariants beat this skill.

You are usually the **lead Agent / 主 Agent**: you split work into tasks, dispatch them, review and merge task PRs once the required checks pass, accept tasks implemented by other Agents, handle blocks, retire branches and keep Issues honest. You go to the disposer only for the three things in PRINCIPLES §1 — start confirmation for a §11 hit, final acceptance, exceptions — always with [templates/decision-request.md](../../templates/decision-request.md). You never accept your own work and never write a disposer reply (`批准 A`, `PHASE ACCEPT`, `FREEZE ACK` or any other wording).

If you are assigned only an execution task, use the [executor skill](../github-multi-agent-task-executor/SKILL.md); do not inherit lead merge/acceptance authority. Reading either skill has no write or dispatch side effect.

## Task protocol / 派发契约

Use exactly the [task sheet](../../templates/ISSUE_TEMPLATE/task.md),
[claim/start comment](../../templates/task-claim.md) and
[completion report](../../templates/task-completion.md) as the shared handoff.
Keep the existing lead entry name; these links are the shared contract, not a
second process or control plane.
Keep field names and the template's literal values exactly; normalize translated
input facts to those values rather than inventing equivalent status spellings.

1. Create a bounded task with inputs/dependencies, allowed files, non-goals,
   acceptance tests and stop rules. In standard link its parent Phase; light
   standalone tasks carry their own freeze. Earlier approval covers only the
   explicitly written scope, never a newly discovered major-change hit.
   Declare actual file/dir paths in `apo-file-scope v1`; before dispatch/START,
   run `project-automation.py dispatch-check --task <number>`. Conflict (3) or
   unknown scope/API (2) stops affected dispatch until sequenced or reconciled.
   Check same-batch candidates against each other. See [automation](../../playbooks/automation.md).
2. Check existing claims/handoffs before assigning. For an unassigned task, CLAIM
   is a request: explicitly confirm the owner on the task and in the authorized
   host assignment before START. Assigned tasks require matching identities.
   Reconcile an existing owner
   explicitly on the Issue; never silently replace it. Actual dispatch uses
   the current host's authorized task mechanism. A GitHub comment alone does
   not start an Agent, and Agent identities are plain text, not mentions.
3. CLAIM registers ownership only and leaves backlog. START requires verified
   contract/approval, available dependencies and real workdir/branch/HEAD from
   the existing workspace workflow and `git -C "<workdir>" rev-parse HEAD`; then
   set the task Issue in-progress and sync CC section 1. A child task does not
   change its parent Phase label; update that only on a real Phase transition.
4. Completion is verification, with per-test evidence, final HEAD/PR and explicit
   failures/unverified facts. Inspect actual checks for that SHA. For a standard
   child task implemented by an executor, after PR merge and acceptance by a non-implementing lead, remove
   its previous status, set `status:done` and close the task. Tasks implemented by the lead,
   light tasks, Phases and releases stay `status:verification` until covered by
   disposer final acceptance; only then set `status:done` and close. Light tasks
   close after release final acceptance covers them (or all confirmed goals are
   finally accepted if no release). In light, lead review and PR merge do not
   constitute task acceptance. The disposer's final acceptance covers task
   acceptance, followed immediately by done/closure; there is no separate lead
   task-acceptance step. An explicit cancel with recorded
   authorization/reason also sets `status:done` and closes the item. Phase/release
   cancellation always requires the disposer's explicit authorization; only
   eligible task cancellations may be authorized by the lead. §11.8 still applies
   when cancellation changes a confirmed goal. Executors cannot merge, close or self-accept. Sync CC section 1 after
   the status/closure transition; a child task does not change its parent Phase.
5. After authorized merge run the existing tidy script, keep CC current and
   request human final acceptance at the Phase/release boundary. No comment,
   check result or task acceptance substitutes for Phase PASS.

## 必读 / Required reading

1. [PRINCIPLES.md](../../PRINCIPLES.md)
2. [playbooks/start-project.md](../../playbooks/start-project.md) — if no Command Center
3. [playbooks/phase-lifecycle.md](../../playbooks/phase-lifecycle.md)
4. [playbooks/staff-and-dispatch.md](../../playbooks/staff-and-dispatch.md)
5. [playbooks/blocked-and-exceptions.md](../../playbooks/blocked-and-exceptions.md)

Companion skills: `git-worktree-and-branch`, `issues-prs-and-evidence`, `project-diagnostics`.

Git landing and worktrees follow [git-worktree-and-branch](../git-worktree-and-branch/SKILL.md). Only GitHub `origin` is supported. Preserve unexpected old remote settings and stop affected writes; no alternative publishing workflow is supplied.

## 工作循环 / Loop

1. Find Command Center. If missing → start-project playbook. Stop implementation.
2. Confirm disposer + roster. If missing → fail closed, comment on a new Command Center draft.
3. Read the process mode (PRINCIPLES §0; unrecorded = `standard`). One Phase (`light`: one task) = one core problem. No `CONTRACT FREEZE` with a `大改动检查` line → no `feat/` / `fix/` branch. On a §11 hit, also wait for the approved start confirmation; work it does not cover keeps moving.
4. Dispatch through the task protocol above. CLAIM leaves backlog; only verified
   START with frozen/approved scope and actual workdir/branch/HEAD moves the task
   to in-progress. Sync CC section 1 and the Phase status when it actually changes.
5. Implement on one branch / one PR (single task: idle primary checkout; parallel: own worktree, capped). Attach replayable evidence to this PR or Issue; a separate evidence PR is optional. After each merge or close, `tidy-worktrees.sh --apply` retires finished work.
6. Before requesting merge or review, inspect the project's actual required CI, code-review and acceptance gates for the current PR SHA. A provider-specific bot is never a generic requirement; passing checks does not imply `PHASE ACCEPT`.
7. Decide everything that is not on §11 yourself (task split, dispatch, review, merging task PRs, blocks, cleanup). Requests that are ready at the same time go out as **one** fixed-format request.
8. At the end of a Phase (`light`: before a release), post one final-acceptance request: acceptance table, known problems, a 1–2 step check for the disposer, latest `apo-tidy:` line. The reply (or legacy `PHASE ACCEPT`) is the only PASS; record it with an `apo-decision-result` marker.
9. Update Command Center **section 1** and the Phase index. Never treat merge as PASS. [ ] **CC §1 updated**


## Command Center hygiene / CC §1（mandatory agent duty）

Keeping Command Center **section 1** current is **Agent work on every gate flip**, not a user habit. It is the project-local, durable summary that a fresh Agent uses to find the current Phase, gates, and next action. A stale summary is misleading even without any external reporting service.

**On every** gate flip / phase status change / Freeze / blocked / verification / Accept event, in the **same turn**:

1. Update Command Center **section 1** (one-glance): current work, status word, pending decisions (“待你决定”), blockers, evidence pointers, **single Next Action**, latest `apo-tidy:` line.
   Use `project-automation.py status` to preview from current GitHub state, inspect
   the table, then apply with the matching plan_id; no hand-built status table.
2. If this event is a Phase **status transition** (dispatch → `in-progress`, blocked, verification, Accept/`done`), update the Phase issue **status label** (`status:backlog` | `in-progress` | `blocked` | `verification` | `done`) and remove the previous status label. **Freeze ACK is not a status-label change** — leave the existing label (usually `status:backlog`) in place.
3. Chat only pings humans to **look at GitHub**. Chat ≠ state.

Phase transition checklist (required checkbox):

- [ ] **CC §1 updated**

If the Agent **cannot** update Command Center (auth, permissions, read-only `gh`, API failure): fail closed. Comment `BLOCKED:` with the gap on the Phase (or a new Command Center draft) and set `status:blocked`. Do **not** leave the new state only in chat.

Playbook copies: [phase-lifecycle.md](../../playbooks/phase-lifecycle.md), [staff-and-dispatch.md](../../playbooks/staff-and-dispatch.md).

In every GitHub comment, including quoted human text, rewrite Agent/bot mentions
as “at name” and note that the quote was safely rewritten. Keep human disposer
identity fields and file-import syntax intact.

## Fail closed

- No methodology (this repo) loaded → refuse to invent a process.
- No business-product content belongs **in** agent-project-ops. Link out only.
- Unknown architecture after Freeze → Architecture Exception issue, not a silent refactor.
- Gate flipped but CC §1 not updated → incomplete; treat as blocked until GitHub reflects it.
- Cannot edit Command Center → `BLOCKED:` on GitHub, not chat-only.

## Do not

- Add Notion, bots, CI bootstrap, or deploy stacks as part of this skill.
- Copy business SOP into the methodology repository.
- Self-label a Phase `status:done` without the disposer's final acceptance.
- Ask the disposer about anything that is not on the §11 list, or send requests one by one when they could be one.
- Post a decision request outside the fixed format, or record a decision the disposer did not give.
- Ask the human to “remember to update CC §1” as the primary path.
- Ask the disposer to merge when required checks are missing or treat automated review as Accept.
