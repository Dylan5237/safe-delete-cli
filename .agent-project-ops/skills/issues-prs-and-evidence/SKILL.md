---
name: issues-prs-and-evidence
description: >
  Keep GitHub Issues as canonical state, use status labels, split implementation
  PRs from evidence PRs, and fail closed when blocked or the freeze must change.
  Use when filing phases, Command Center, Architecture Exception, verification,
  or PR templates.
---

# Issues, PRs, and evidence

**Chat ≠ state.** If it is not on the Issue, PR, or git object, it did not happen.

## Playbooks

- [playbooks/issues-and-prs.md](../../playbooks/issues-and-prs.md)
- [playbooks/verification-and-evidence.md](../../playbooks/verification-and-evidence.md)
- [playbooks/blocked-and-exceptions.md](../../playbooks/blocked-and-exceptions.md)
- Templates: [templates/](../../templates/) · Labels: [templates/labels.md](../../templates/labels.md)

## Status (exactly one per issue)

`status:backlog` | `status:in-progress` | `status:blocked` | `status:verification` | `status:done`

## PR split (Principle 9)

| PR kind | Branch prefix | Template | Contains |
| --- | --- | --- | --- |
| Implementation | `feat/` `fix/` `docs/` | `templates/PULL_REQUEST_TEMPLATE/implementation.md` | product/library/test **code** |
| Evidence | `evidence/` | `templates/PULL_REQUEST_TEMPLATE/evidence.md` | replayable proofs only |

PR merge ≠ Phase PASS. Propose `EVIDENCE READY`; disposer writes `PHASE ACCEPT`.

## Agent checklist

1. Link every branch to an Issue. Empty issue bodies are invalid.
2. Copy Freeze text / ACK into the implementation PR.
3. Map each frozen acceptance test → proof (table).
4. On gaps: `BLOCKED:` comment + `status:blocked`.
5. Frozen field wrong → new Architecture Exception issue; do not edit-and-continue.
6. Redact secrets from logs.

Do not add a second control plane (chat logs, unofficial boards) as a substitute.
