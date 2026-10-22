# Playbook: Blocked and Architecture Exception / 阻塞与架构例外

## Goal

Stop when the contract or environment is insufficient (**fail closed**), and route contract changes that need the disposer through an **exception request** (fixed format, `templates/decision-request.md`, type `例外`) instead of a quiet edit.

## When

- Missing freeze, credentials, `origin`, a required start confirmation, or evidence.
- Implementation discovers the frozen contract is wrong or incomplete.
- Two Phases collide; scope must change.

## Preconditions

- Phase or task Issue exists.
- Command Center names the disposer.
- Agent will not continue implementation on a disputed freeze.

## Steps

### A. Blocked / 阻塞

1. Set **exactly** `status:blocked` (remove `in-progress` if it was set).
2. Comment `BLOCKED:` plus a checklist of gaps, last good SHA, branch and working directory, and **what would unblock**.
3. Park the task: commit WIP on the topic branch, `git push -u origin HEAD`, then `tidy-worktrees.sh --park <branch>` (branch kept locally and on origin; the folder is released, or the primary checkout returns to the default branch). `git stash` is not parking — a stash is local-only and invisible to the next Agent. Resume later with `new-worktree.sh` (same issue, slug and kind).
4. Do not open unrelated `feat/` work “to stay productive” against the same Phase.
5. When unblocked: comment `UNBLOCKED:` with proof, restore `status:in-progress` or `verification`.
6. Update Command Center **section 1** on both block and unblock. [ ] **CC §1 updated**. If CC cannot be edited, the `BLOCKED:` comment on the Issue is still required; do not leave the gap chat-only.
7. Waiting for a disposer reply is **not** blocked: the covered Issue keeps its status label, the request is listed under “待你决定” in CC §1, and unaffected tasks keep moving. Use `status:blocked` only for a real gap.

### B. Exception / 例外

Use when a **frozen** contract must change in a way that hits `PRINCIPLES.md` §11, goes beyond the confirmed goal, or removes or loosens a confirmed acceptance test or NON-GOAL. Other contract edits (clarifying wording, splitting into tasks, adding tests) need no exception: the lead Agent posts a new `CONTRACT FREEZE` with a one-line diff note.

1. Open an issue with `templates/ISSUE_TEMPLATE/architecture-exception.md`. Labels: `type:exception` + `status:backlog`.
2. Link the Phase. State: current frozen text, proposed text, why fail-closed triggered, impact on in-flight PRs (rebase / close / split Phase).
3. The lead Agent posts the request on that issue (`templates/decision-request.md`, type `例外`) and lists it under “待你决定” in CC §1. The disposer replies `批准 A` / `改用 B` / `退回：<原因>` (legacy `EXCEPTION ACCEPT` / `EXCEPTION REJECT` still count).
4. Only after approval:
   - Update the Phase body.
   - Post a new `CONTRACT FREEZE` comment (new date).
   - Close or retarget PRs that assumed the old freeze.
5. If returned: keep the original freeze; the Phase stays blocked or returns to implementation under the old contract.

### C. Cancel / supersede

Disposer may close a Phase with `SUPERSEDED BY #n` without Accept. Record it on Command Center. Do not reuse the old issue number for a new core problem.

## Done when

- [ ] Blocked issues have an explicit gap list.
- [ ] No implementation commits after a disputed freeze without an approved exception request.
- [ ] Approved exceptions produce a new Freeze comment.
- [ ] Command Center lists open exceptions.
- [ ] **CC §1 updated** (or GitHub `BLOCKED:` states why §1 could not be rewritten).

## Anti-patterns

- Editing the Phase body and continuing to code.
- `status:blocked` with no comment.
- Exception issue that is actually a new product idea (that is a new Phase).
- An Agent approving an exception (`EXCEPTION ACCEPT`, `批准 A` or any other wording).
- Opening a second remote or a fork-only workflow to dodge protection or review. Only GitHub origin is supported; unavailable origin is a blocker.
