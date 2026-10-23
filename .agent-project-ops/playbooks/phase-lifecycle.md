# Playbook: Phase lifecycle / 阶段生命周期

## Goal

Move a Phase from idea to **CLOSED** with a frozen contract, isolated implementation, replayable evidence, and the disposer's final acceptance. Merge is not PASS. The disposer is asked only at the points in `PRINCIPLES.md` §1 (start confirmation for a §11 hit, final acceptance, exceptions), always with `templates/decision-request.md`; everything else is the lead Agent's call.

**Process mode** (`PRINCIPLES.md` §0; `process_mode` in `.agent-project-ops/project-config`, unrecorded = `standard`):

- `standard`: the steps below run once per Phase.
- `light`: there are no Phase issues. Each task uses the [task sheet](../templates/ISSUE_TEMPLATE/task.md), label `type:task`, carries its own contract and runs steps 1–3. Step 4's final acceptance runs once before each release, in one request of type `最终验收+发布` that lists every task since the last release (a project that never releases asks when all confirmed goals are done); step 5 then closes the tasks it covered.

In light, the lead's technical review and PR merge do not accept a task. Task
acceptance is covered by the disposer's final acceptance in step 4 and is followed
immediately by done/closure in step 5, without a separate lead task-acceptance step.

## When

- A Phase issue exists (`type:phase`); in `light` mode, a task issue (`type:task`).
- You are about to write code, verify, Accept, or close.

## Preconditions

- Command Center is open and names the disposer.
- The Phase states **one** core problem (Principle 6).
- Agent loaded `PRINCIPLES.md`. Fail closed if the freeze (or a required start confirmation) is missing.

## Steps

Every transition below includes: update Command Center **section 1** in the same turn, and check **「CC §1 updated」**. This is **mandatory Agent duty**, not a user habit. If CC cannot be updated → `BLOCKED:` on GitHub (not chat-only). See `skills/github-multi-agent-project-ops`.

### 0. Status labels (on the Phase issue)

Use exactly: `status:backlog` → `status:in-progress` → (`status:blocked` if needed) → `status:verification` → `status:done`. Remove the previous status when transitioning. Then update CC §1 (current phase, status word, gates, **single Next Action**).

- [ ] **CC §1 updated**

### 1. Freeze / 冻结合同

1. Fill the Phase template: in-scope, out-of-scope (NON-GOALS), acceptance tests, interfaces/data contracts, risks, owner.
2. **Major-change check.** Compare the contract with `PRINCIPLES.md` §11 item by item. Unsure = hit.
3. Post a **Freeze** comment: `CONTRACT FREEZE <ISO-8601 date>`, the frozen bullet list (or a permalink to the issue body revision) and the line `大改动检查：无` or `大改动检查：命中第 N 条（…）`.
4. **Hit** → post a start confirmation (`templates/decision-request.md`, type `开工确认`), merged with any other request that is ready at the same time, and list it under “待你决定” in CC §1. Wait for the disposer's reply (`批准 A`; legacy `FREEZE ACK` counts). Agents never answer it. Work it does not cover keeps moving. Exception: if an approved start confirmation already pre-approved this Phase (`PRINCIPLES.md` §4 **Pre-approval**) and the contract stays inside that plan, write `大改动检查：命中第 N 条，已由 D-n 提前批准` with the link and skip the new request.
5. **No hit** → the lead Agent's `CONTRACT FREEZE` is the go-ahead; nobody waits for a human.
6. Update CC §1 (status word, pending decisions, Next Action). [ ] **CC §1 updated**
7. Only then may implementation branches be created. Re-check §11 whenever a task is dispatched or the planned change grows; a new hit needs its own request.

### 2. Implement / 实现

1. One branch per task/PR, on the idle primary checkout or its own worktree (`playbooks/git-worktree.md`, `git-branch-and-remote.md`).
   Use the task sheet plus [claim/start](../templates/task-claim.md) and
   [completion](../templates/task-completion.md) records. CLAIM is not permission
   to start; valid START needs frozen scope, required approval and actual baseline.
   Agent identities in claim/start comments are plain text, never mentions.
2. Implementation PRs use `templates/PULL_REQUEST_TEMPLATE/implementation.md`.
3. Link `Closes` / `Refs` the Phase or child task issue.
4. Do not “improve” frozen fields in the same PR. A change that hits §11, goes beyond the confirmed goal or loosens a confirmed acceptance test is an exception request (`playbooks/blocked-and-exceptions.md` B); anything else is a new `CONTRACT FREEZE` with a one-line diff note.
5. Update CC §1 when the implementation PR opens or the Phase label moves. [ ] **CC §1 updated**
6. Before asking for merge/review, check actual mandatory CI and review gates for the current PR SHA using `playbooks/issues-and-prs.md` step 8.
7. The lead Agent reviews each task PR against the task's acceptance tests and merges it once the required checks pass (unless merging releases or deploys: §11 item 4). For a standard child task implemented by an executor, after PR merge and acceptance by a non-implementing lead, remove its previous status, set `status:done` and close the task. Tasks implemented by the lead, light tasks, Phases and releases stay `status:verification` until covered by disposer final acceptance; only then set `status:done` and close. Light tasks close after release final acceptance covers them (or all confirmed goals are finally accepted if no release); step 5 closes those covered tasks. In light, lead review and PR merge do not constitute task acceptance. The disposer's final acceptance covers task acceptance, followed immediately by done/closure; there is no separate lead task-acceptance step. An explicit cancel with recorded authorization/reason also sets `status:done` and closes the item. Phase/release cancellation always requires the disposer's explicit authorization; only eligible task cancellations may be authorized by the lead, subject to §11.8 when they change a confirmed goal.
8. After each PR merges or closes, run `tidy-worktrees.sh --apply`: merged work is retired, closed work is archived first, everything unproven is kept and listed.

### 3. Verify / 验证

1. After the implementation PR is reviewable (merged or merge-ready per Command Center policy, respecting required CI/reviewer gates before asking for merge), attach replayable evidence to the implementation PR or Issue; a separate evidence PR is optional (`playbooks/verification-and-evidence.md`).
2. Label Phase `status:verification`.
3. Evidence must be replayable by the disposer without the original chat.
4. Update CC §1. [ ] **CC §1 updated**

### 4. Accept / 最终验收

1. Run `tidy-worktrees.sh --apply` first. Every folder or branch it still keeps for this Phase is retired, parked or listed with a reason.
2. The lead Agent posts **one** final-acceptance request (`templates/decision-request.md`, type `最终验收`): the acceptance table (each frozen acceptance test → result, evidence, verdict), known problems, a 1–2 step way for the disposer to check it, and the `apo-tidy:` line. List it under “待你决定” in CC §1.
3. Several Phases ready at the same time → one request with all of them in `target`. After the reply, post the `apo-decision-result` marker in the request's thread and a link to it on every target (a reference, not a new decision).
4. The disposer's reply — `批准 A` / `改用 B` / `退回：<原因>`, or the legacy `PHASE ACCEPT` / `PHASE RETURN` — is the only PASS or return. PR merge, CI green and automated or human review do not substitute, and no Agent writes the reply.
5. After the reply, update CC §1 (do not treat merge as PASS). [ ] **CC §1 updated**

### 5. CLOSED

1. After recorded disposer final acceptance, remove the previous status and set `status:done`. Close the Phase issue when leftover tasks are closed or moved to a new Phase. In light mode, instead set the covered tasks `status:done` and close them after release final acceptance (or final acceptance of all confirmed goals if no release). A recorded explicit cancel/supersede also sets `status:done` and closes the item. Phase/release cancellation always requires the disposer's explicit authorization, even without a change of confirmed goals; only eligible task cancellations may be authorized by the lead, subject to §11.8.
2. Link the Command Center index to the closed Phase (table row: issue number, date, result).
3. Update CC §1 (current phase, status word, Next Action). [ ] **CC §1 updated**

If blocked at any step: `playbooks/blocked-and-exceptions.md`. Do not skip the freeze or the final acceptance. Blocked also updates CC §1.

Generate CC section 1 using the status preview/apply command described in
[automation](automation.md), after recording the real Issue labels and decisions.
Do not infer final acceptance. In any GitHub comment, including human quotations,
rewrite Agent/bot mentions as “at name” and note the safe rewrite.

## Done when

- [ ] The freeze carries a `大改动检查` line; on a hit, the start confirmation was approved (legacy `FREEZE ACK` counts).
- [ ] Each frozen acceptance test has replayable proof in the task PR or Issue; a separate evidence PR is optional.
- [ ] The disposer's final acceptance (`批准 …` on a `最终验收` request, or legacy `PHASE ACCEPT`) or an explicit cancel/supersede note is on the issue.
- [ ] Phase is `status:done` and closed, or still open only because a documented follow-on Phase owns remaining work.
- [ ] Command Center index updated.
- [ ] The final-acceptance request carried an `apo-tidy:` line with `failed=0`; no leftover folder or branch of this Phase is unexplained.
- [ ] **CC §1 updated** on each gate flip recorded above (current phase, status word, gates, single Next Action).

## Anti-patterns

- Coding on `main`, before the freeze, or on a §11 hit before the start confirmation is approved.
- Asking the disposer about anything that is not on the §11 list, or sending requests one by one when they could have gone out as one.
- A decision request outside the fixed format (`templates/decision-request.md`), or an Agent writing, paraphrasing or “assuming” the disposer's reply.
- Requesting final acceptance while finished task folders/branches of this Phase are still lying around unexplained.
- “We merged, so the phase passed.”
- Asking the disposer to merge with unmet mandatory CI/reviewer gates, or treating checks as Accept.
- Flipping a Phase label or Freeze/blocked/verification event without updating Command Center §1 (leaving the new state in chat).
- Quietly editing the frozen contract in a later commit message.
- One Phase with two unrelated acceptance suites.
- Any Agent accepting its own work, or commenting `PHASE ACCEPT` / `批准 A` as if it were the disposer.
