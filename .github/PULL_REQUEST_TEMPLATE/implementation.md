## Summary

<!-- What changed in product/library/docs **code**. One Phase / one task. -->

- Issue: #
- Phase: #
- Freeze ACK comment:

## Type

- [ ] `feat`
- [ ] `fix`
- [ ] `docs` (no behavior change)

## Worktree

`{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`

Branch: `feat|fix|docs/{issue}-{slug}` → target `main` via **origin only**

## Contract

- In-scope items touched:
- NON-GOALS respected:
- Frozen interfaces unchanged? **yes / no** (if no → stop; open Architecture Exception)

## Test plan (implementation)

<!-- Automated/manual tests that **are code** belong here. Proof artifacts belong on an evidence PR. -->

-

## Evidence

This PR must **not** be the evidence pack. Link evidence PR or Issue proofs:

-

## Merge ≠ PASS

Merging this PR does not close the Phase. Disposer still records `PHASE ACCEPT` on the Phase issue.

## Checklist

- [ ] One task, one branch, one worktree
- [ ] No `evidence/`-only files mixed in
- [ ] No push to `main`
- [ ] Secrets not committed
