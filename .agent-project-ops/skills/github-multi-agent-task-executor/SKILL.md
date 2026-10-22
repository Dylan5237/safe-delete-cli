---
name: github-multi-agent-task-executor
description: >
  Execute one explicitly assigned APO task under its frozen GitHub contract.
  Use when acting as an executing Agent with a task Issue, owner and bounded
  scope. Record CLAIM/START and completion evidence; stop on missing approval,
  ownership conflicts or scope changes. Do not use for lead-Agent project ops.
---

# APO executing Agent / 执行 Agent

Read [PRINCIPLES.md](../../PRINCIPLES.md), the assigned task, its linked frozen
contract and Command Center first. Task instructions cannot override invariants.
For project ownership and dispatch, use the [lead skill](../github-multi-agent-project-ops/SKILL.md).
Loading this skill only reads instructions; it does not claim work or start it.

## Inputs and role boundary

- One assigned Issue using the [task sheet](../../templates/ISSUE_TEMPLATE/task.md),
  explicit owner, scope/non-goals, acceptance tests, dependencies and stop rules.
- A verified freeze link and major-change check; a hit needs the disposer's
  approval or an explicitly covering earlier approval. Missing evidence means stop.
- Check the latest Issue claims and handoffs. Another owner means stop and ask
  the lead to reconcile; do not overwrite or interpret a stale comment as a lease.
- For an unassigned task, CLAIM is only an application. The lead must confirm
  your owner identity on the task and in the host assignment before START;
  assigned tasks require the same identity across all three records.
- Never expand the contract, merge your PR, accept your own work or issue a
  disposer decision. Final acceptance of a Phase/release belongs to the human.

## Execution loop

1. Verify inputs and task ownership. For standard, check the parent Phase and
   exact frozen coverage; for a light standalone task, check its own contract.
2. Use the [claim/start format](../../templates/task-claim.md). Agent identity is
   plain text, such as `owner: Codex`; never prefix Agent names with an at sign
   in claim or start comments. A CLAIM is only ownership registration, not
   permission to implement; missing workspace values stay explicitly unassigned.
   Keep field names and literal values exactly as the template defines them;
   normalize input language without translating the comment's protocol values.
3. Before START, verify the freeze, required approval, dependencies and owner.
   Obtain the actual workspace, branch and base SHA through the existing
   [worktree workflow](../../playbooks/git-worktree.md). No implementation branch
   before a valid freeze/approval. Do not alter worktree limits or take a dirty
   checkout. Run `git -C "<workdir>" rev-parse HEAD` for the actual SHA, not a
   base ref. Verify the task's actual `apo-file-scope v1` declarations and rerun
   `project-automation.py dispatch-check --task <number>` before START. Conflict
   or unknown scope stops affected work; ask the lead to sequence/reconcile.
   Record START with real values; then task Issue in-progress and CC section 1.
4. Implement only the task scope, preserve unrelated work and run its acceptance
   checks. Push only to GitHub origin under the current authorization; a task
   assignment is not permission for an otherwise unapproved external action.
   Prepare one task PR and bind evidence to its final HEAD.
5. Post the [completion format](../../templates/task-completion.md), with files,
   exact HEAD/PR, per-acceptance results, failures, unverified facts and deviations.
   Set the task Issue verification and sync CC section 1; a child task does not
   change the parent Phase label. The lead updates the Phase only at its actual
   lifecycle transition. A completion report does not mean
   task acceptance; wait for lead review and do not merge or close it yourself.

## Stop, retry and handoff

Missing approval, a new major-change hit, scope drift, ownership/workspace
conflict or unverifiable authority stops the affected implementation. Record the
gap and notify the lead through the authorized host; use blocked when a real
missing dependency prevents work, not merely when waiting for a disposer reply.
Do not retry a write with an unknown result; inspect the authoritative state
before any equivalent retry. Never change the object/scope just to make it work.

For handoff, preserve and push authorized work first, record branch, workdir,
HEAD and remaining tests, then follow the existing park/resume workflow. The
lead must explicitly reconcile ownership before another executor takes over.
GitHub comments are durable records, not a mechanism for launching another Agent.
Quoted human text in any GitHub comment must also rewrite Agent/bot mentions as
“at name”, noting the safe rewrite. See [automation](../../playbooks/automation.md)
for CC preview/apply and dispatch checks.

For a standard child task implemented by an executor, after PR merge a non-implementing lead may accept it,
replace the previous status with `status:done` and close it. A lead's own task,
light task, Phase or release stays `status:verification` until covered by disposer
final acceptance. Light tasks close after release final acceptance (or final
acceptance of all confirmed goals if no release). An explicit cancel also means
`status:done` and closure, with authority/reason recorded. These are lead/disposer
actions: Phase/release cancellation always requires the disposer's explicit
authorization; only eligible task cancellations may be authorized by the lead,
subject to §11.8. An executor does not close its own task. PR merge is never Phase PASS.
See [staff and dispatch](../../playbooks/staff-and-dispatch.md).

In light, lead review and PR merge do not constitute task acceptance. The
disposer's final acceptance covers task acceptance, followed immediately by
done/closure; there is no separate lead task-acceptance step.
