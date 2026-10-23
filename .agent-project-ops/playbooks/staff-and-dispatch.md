# Playbook: Staff and dispatch / 编制与分派

## Goal

Make it obvious **who decides what** (`PRINCIPLES.md` §1: the disposer decides only start confirmations for §11 hits, final acceptance and exceptions; the lead Agent decides the rest) and **which Agent owns which working directory** (the primary checkout or a worktree), without a second control plane.

## When

- Starting a project (after Command Center exists).
- Adding a second local Agent or a human reviewer.
- A task is ready to leave `backlog`.

## Preconditions

- Command Center issue exists.
- Labels from `templates/labels.md` exist.
- A single task runs on the idle primary checkout; each additional concurrent task gets its own worktree, at most `max_worktrees` folders (default 3) (Principle 8).

## Steps

1. **Name the disposer** on Command Center (the human's GitHub handle). The disposer answers fixed-format requests (`templates/decision-request.md`) for start confirmations on §11 hits, final acceptance and exceptions — nothing else.
2. **Name the lead Agent / 主 Agent** (often the local coding Agent). It splits work into tasks, dispatches, reviews and merges task PRs once the required checks pass, accepts tasks implemented by other Agents, handles blocks, retires branches and refuses illegal shortcuts. It never accepts its own work and never answers a request to the disposer. Requests that are ready at the same time go out as one. **Mandatory duty:** on every gate flip / phase status / Freeze / blocked / verification, update Command Center **section 1** in the same turn. Update the Phase status label only when the Phase status actually changes (a freeze or its start confirmation is not a label change). Chat only pings humans to look at GitHub. If CC cannot be updated → `BLOCKED:` on GitHub, not chat-only. [ ] **CC §1 updated**
3. **Roster table** on Command Center:

   | Role | Handle / Agent id | May merge? | May accept? |
   | --- | --- | --- | --- |
   | Disposer | | yes | final acceptance (Phase or release) |
   | Lead Agent | | task PRs after required checks (a merge that releases or deploys is §11 item 4) | tasks it did not implement |
   | Executing Agent | | no | no |
   | Reviewer (optional) | | no | no |

4. **Dispatch a task:**
   - Use the [task sheet](../templates/ISSUE_TEMPLATE/task.md): one core problem,
     explicit owner, scope/non-goals, dependencies, acceptance tests and stop rules.
     Standard tasks link the parent Phase; light standalone tasks carry their own contract.
   - Check existing claims/handoffs before assigning. Another owner requires an
     explicit reconciliation by the lead; never overwrite or silently take over.
     A CLAIM on an unassigned task is only an application; the lead confirms the
     owner on the task and in the host assignment before valid START. Already
     assigned tasks require matching owner identities in all records.
   - Before creating an implementation branch, verify the task's frozen contract
     and re-check `PRINCIPLES.md` §11. A hit needs the covering approval; a new
     hit waits for its own confirmation while unaffected tasks go ahead.
   - Declare actual file/dir paths in the task's `apo-file-scope v1` block. Run
     `project-automation.py dispatch-check --task <number>` immediately before
     dispatch/START; code 3 lists overlaps with other active tasks, code 2 means
     unknown scope/API failure. Resolve by sequencing or reviewing scope first;
     do not dispatch on an unknown/conflicting result. Check batch candidates
     against each other too. See [automation](automation.md).
   - Only after that gate, run `new-worktree.sh` per git playbooks. It retires finished work first, then puts the task on the idle primary checkout or a new worktree. **Exit 3** = folder cap reached, nothing created: leave the Issue `status:backlog`, comment `QUEUED: folder cap (n/max)`, and dispatch it when a running task merges or is parked.
   - Use the [claim/start comment](../templates/task-claim.md). CLAIM registers
     ownership only and leaves backlog; it does not authorize implementation.
     After verifying freeze/approval, dependencies and ownership, record START
     with actual workdir, branch and HEAD from the helper. Pending values cannot start work.
     The helper provides workdir/branch/base; obtain the actual complete HEAD
     with `git -C "<workdir>" rev-parse HEAD`, never substitute the base ref.
   - Claim and start comments use plain Agent names (for example `owner: Codex`),
     never an at sign followed by an Agent name. Human disposer identity fields
     are unchanged. Send the task through the current host's authorized task
     mechanism; GitHub records alone do not launch Agents or external bots.
   - Only after valid START set the task Issue `status:in-progress`. Assign the GitHub issue if the host is used.
   - Update Command Center §1 (current phase, status word, **single Next Action**). [ ] **CC §1 updated**
5. **Completion and handoff:** use the [completion report](../templates/task-completion.md)
   with final HEAD/PR, changed files, acceptance evidence, failures, unverified
   facts and contract deviations. Set the task Issue verification and sync CC.
   A standard child task does not change its parent Phase label; the lead updates
   the Phase only when the Phase lifecycle actually changes. The executor
   does not merge, close or self-accept. For a standard child task implemented by an executor, after PR merge
   and acceptance by a non-implementing lead, remove its previous status, set
   `status:done` and close the task. Tasks implemented by the lead, light tasks, Phases and
   releases stay `status:verification` until covered by disposer final acceptance;
   only then set `status:done` and close. Light tasks close after release final
   acceptance covers them (or all confirmed goals are finally accepted if no release).
   In light, lead review and PR merge do not constitute task acceptance. The
   disposer's final acceptance covers task acceptance, followed immediately by
   done/closure; there is no separate lead task-acceptance step.
   An explicit cancel with recorded authorization/reason also sets `status:done`
   and closes the item. Phase/release cancellation always requires the disposer's
   explicit authorization; only eligible task cancellations may be authorized by
   the lead. §11.8 still requires approval when cancellation changes a confirmed goal.
   For handoff, commit and push authorized work first (never stash; never leave mystery dirty trees), then comment `HANDOFF to <id>` with branch, working directory and head SHA. The lead reconciles the owner on the Issue before the next Agent claims it. If the next Agent works in a different place, `tidy-worktrees.sh --park <branch>` releases the folder and it resumes with `new-worktree.sh` (same issue, slug and kind; the owner may change).
6. **Recall:** if scope drifts, the disposer or the lead Agent comments `STOP` or `RETURN TO BACKLOG`. The executing Agent commits and pushes, parks with `tidy-worktrees.sh --park <branch>` (branch kept, folder released), sets `status:backlog` or `blocked`, and updates CC §1. To abandon the task instead, close its PR and run `tidy-worktrees.sh --abandon <branch>` (archive tag first, then delete); that is the lead Agent's call unless dropping the task changes a confirmed goal (§11 item 8 → ask the disposer). [ ] **CC §1 updated**
7. **Parallelism:** the first task may use the idle primary checkout; every further concurrent task gets its own worktree, at most `max_worktrees` folders. Never stack two tasks in one directory. More tasks than slots ⇒ queue (step 4), never bypass the cap.
8. **After merge or close:** run `tidy-worktrees.sh --apply` and put its `apo-tidy:` line in the status report. Anything it keeps is listed with a reason; resolve `stale` entries or name their owner.

Generate CC section 1 with `project-automation.py status`: preview, inspect the
table, then apply the unchanged plan_id. Keep status/decision records on GitHub
first; see [automation](automation.md). When quoting humans in any GitHub comment,
rewrite Agent/bot mentions as “at name” and note the safe rewrite.

## Done when

- [ ] Command Center roster is complete.
- [ ] Every `in-progress` issue names an owner in the last dispatch comment.
- [ ] Claim/start and completion records use the shared templates; no Agent mentions in claim/start comments.
- [ ] **CC §1 updated** after dispatch, handoff, recall, or status change (or `BLOCKED:` on GitHub if CC cannot be edited).
- [ ] No two in-progress tasks share a working directory, and worktree folders ≤ `max_worktrees`.
- [ ] The latest status report carries an `apo-tidy:` line with `failed=0`.
- [ ] Agents can answer “who decides what, and who accepts?” from the Command Center body alone.

## Anti-patterns

- “Everyone owns it” (nobody disposes).
- One worktree, two Agents, two features.
- Getting past the folder cap by deleting another task's folder or raising `max_worktrees` mid-dispatch.
- Dispatch via chat only; Issue stays `backlog`.
- Treating CC §1 refresh as the human’s habit instead of the lead Agent’s duty.
- Any Agent accepting its own work because “I am the project owner.”
- Sending the disposer questions that are not on the §11 list.
- Staffing an unrelated external workflow as part of this methodology (out of scope).
