# Playbook: Blocked and Architecture Exception / 阻塞与架构例外

## Goal

Stop when the contract or environment is insufficient (**fail closed**), and route contract changes through an **Architecture Exception** issue instead of a quiet edit.

## When

- Missing Freeze, credentials, `origin`, disposer ACK, or evidence.
- Implementation discovers the frozen contract is wrong or incomplete.
- Two Phases collide; scope must change.

## Preconditions

- Phase or task Issue exists.
- Command Center names the disposer.
- Agent will not continue implementation on a disputed freeze.

## Steps

### A. Blocked / 阻塞

1. Set **exactly** `status:blocked` (remove `in-progress` if it was set).
2. Comment `BLOCKED:` plus a checklist of gaps, last good SHA, worktree path, and **what would unblock**.
3. Park the worktree: commit WIP on the topic branch **or** stash and push the branch so another Agent can resume. Do not leave the only copy on one laptop unsynced if others must continue.
4. Do not open unrelated `feat/` work “to stay productive” against the same Phase.
5. When unblocked: comment `UNBLOCKED:` with proof, restore `status:in-progress` or `verification`.

### B. Architecture Exception / 架构例外

Use when a **frozen** field must change (scope, NON-GOALS, interfaces, acceptance tests, data contract).

1. Open an issue with `templates/ISSUE_TEMPLATE/architecture-exception.md`. Labels: `type:exception` + `status:backlog`.
2. Link the Phase. State: current frozen text, proposed text, why fail-closed triggered, impact on in-flight PRs (rebase / close / split Phase).
3. Agent **proposes** the exception; disposer comments `EXCEPTION ACCEPT` or `EXCEPTION REJECT`.
4. Only after `EXCEPTION ACCEPT`:
   - Update the Phase body.
   - Post a new `CONTRACT FREEZE` comment (new date).
   - Close or retarget PRs that assumed the old freeze.
5. If rejected: keep original freeze; Phase stays blocked or returns to implement under the old contract.

### C. Cancel / supersede

Disposer may close a Phase with `SUPERSEDED BY #n` without Accept. Record it on Command Center. Do not reuse the old issue number for a new core problem.

## Done when

- [ ] Blocked issues have an explicit gap list.
- [ ] No implementation commits after a disputed freeze without Exception Accept.
- [ ] Accepted exceptions produce a new Freeze comment.
- [ ] Command Center lists open exceptions.

## Anti-patterns

- Editing the Phase body and continuing to code.
- `status:blocked` with no comment.
- Exception issue that is actually a new product idea (that is a new Phase).
- Agent commenting `EXCEPTION ACCEPT`.
- Opening a second remote or a fork-only workflow to dodge protection or review (a named **projection** mirror is not a dodge; see `playbooks/git-authority-and-projection.md`).
