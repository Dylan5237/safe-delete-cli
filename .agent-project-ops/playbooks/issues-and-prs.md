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
   - Task: use [task sheet](../templates/ISSUE_TEMPLATE/task.md) for a standard
     Phase child task or a light standalone task; still one PR per task.
   - Architecture Exception: frozen-contract change request.
2. **Status label (exactly one):**
   - `status:backlog` — not started
   - `status:in-progress` — dispatched, worktree exists
   - `status:blocked` — cannot proceed; gap listed
   - `status:verification` — implementation proposed; evidence in flight or waiting Accept
   - `status:done` — a standard child task implemented by an executor, accepted by a non-implementing lead after PR merge; a task implemented by its lead, light task, Phase or release covered by disposer final acceptance; or an explicit cancel. See step 9.
3. **Type labels:** `type:command-center` | `type:phase` | `type:task` | `type:exception` | `type:docs`
4. **Open implementation PR** with `templates/PULL_REQUEST_TEMPLATE/implementation.md`.
   - Title: `{type}(#{issue}): short slug`
   - Body: links Issue, Freeze permalink, test plan, NON-GOALS respected.
   - Label PR `pr:implementation`. Do not add product-only labels from a business SOP pack.
5. **Attach evidence** to the task PR or Issue. A separate `evidence/{issue}-{slug}` PR with the optional evidence template/label is available when useful; it is not required.
6. **Comments are the log.** Status changes get a one-line reason. Paste command output **summaries** that matter; do not dump secrets.
   Use [claim/start](../templates/task-claim.md) and
   [completion](../templates/task-completion.md) comments. Agent names are plain
   text; claim/start comments must not mention Agents. CLAIM leaves backlog;
   verified START moves to in-progress; completion moves to verification.
7. **CC §1 on every status/gate change.** Same turn: rewrite Command Center section 1 and keep exactly one Phase `status:*` label. [ ] **CC §1 updated**. If CC cannot be edited → `BLOCKED:` on GitHub, not chat-only.
8. **Required checks before merge-ask.** Inspect the project's actual mandatory CI, code-review and acceptance conditions for the current PR SHA.
   1. If CI or reviewer gates are required, obtain their actual results before requesting a merge. Missing or failed mandatory checks are blockers.
   2. An additional review tool may be used only when it belongs to that project's own policy; generic APO does not install or wake a vendor-specific bot.
   3. Summarize completed, pending and failed checks. CI, automated review and PR merge do **not** constitute `PHASE ACCEPT`.
9. **Close rules.** For a standard child task implemented by an executor, after PR merge and acceptance by a
   non-implementing lead, remove its previous status, set `status:done` and close
   the task. This does not change the parent Phase's status or final acceptance.
   Tasks implemented by the lead, light tasks, Phases and releases stay `status:verification`
   until covered by disposer final acceptance; only then set `status:done` and close.
   Light tasks close after release final acceptance covers them (or after all
   confirmed goals are finally accepted when the project never releases).
   In light, lead review and PR merge do not constitute task acceptance. The
   disposer's final acceptance covers task acceptance, followed immediately by
   done/closure; there is no separate lead task-acceptance step.
   An explicit cancel, with authorization and reason recorded, also sets
   `status:done` and closes the item. Phase/release cancellation always requires
   the disposer's explicit authorization; only eligible task cancellations may be
   authorized by the lead. Changing a confirmed goal still needs §11.8 approval.
   Closing a PR alone does not close or accept a task/Phase.

## Done when

- [ ] Every in-flight branch has a linked open Issue.
- [ ] Exactly one `status:*` label on each tracked Issue.
- [ ] Each PR explains its scope and links replayable evidence; a separate evidence PR is optional.
- [ ] Command Center table lists open Phases.
- [ ] **CC §1 updated** for the latest status/gate flip (or `BLOCKED:` recorded on GitHub).
- [ ] Merge-ask checked required CI/review conditions for the current SHA; missing gates were disclosed.

## Anti-patterns

- Issues with empty bodies (“fix it”).
- Five status labels at once.
- PR with no linked Issue.
- Using Projects/boards as the only state and leaving Issues blank.
- Merging then deleting the Issue before Accept is recorded.
- Changing a Phase status label without rewriting Command Center §1 (or recording `BLOCKED:` on GitHub).
