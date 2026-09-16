# Playbook: Verification and evidence / 验证与证据

## Goal

Make Phase Accept **replayable**: a disposer who was not in the chat can follow evidence to the frozen acceptance tests. Keep evidence PRs distinct from implementation PRs.

## When

- Implementation is reviewable or merged per Command Center policy.
- Phase is entering `status:verification`.
- Agent wants to propose `PHASE PASS` (proposal only).

## Preconditions

- Freeze ACK exists.
- Acceptance tests on the Phase issue are the only bar.
- No secrets in evidence (redact tokens, customer data, `.env`).

## Steps

1. **Map tests to proofs.** Table on the Phase or evidence PR:

   | Frozen acceptance test | Proof | Location |
   | --- | --- | --- |
   | … | command + exit | `evidence/…` or comment gist permalink |

2. **Prefer in-repo evidence** when the business repo already stores fixtures/docs: open `evidence/{issue}-{slug}` and `templates/PULL_REQUEST_TEMPLATE/evidence.md`.
   - Allowed: logs **excerpts**, screenshots, test runner output, curl transcripts, seed scripts used **only** to reproduce.
   - Forbidden: feature code, refactors, dependency bumps “while we’re here.”
3. **If evidence cannot live in git** (binary size, secrets): attach to the Issue comment or a **private** gist and paste the URL on the Phase. Still no mix with implementation commits.
4. **Agent proposes.** Comment `EVIDENCE READY` + table. Do not comment `PHASE ACCEPT`.
5. **Disposer verifies** by replaying at least the critical path (or records why replay was sampled). Then `PHASE ACCEPT` or `PHASE RETURN` with failing test ids.
6. **Fail closed.** Missing proof for any frozen test → `status:blocked` or remain in `verification`, never `done`.

## Done when

- [ ] Every frozen acceptance test has a proof link.
- [ ] Evidence PR (if any) contains **zero** implementation diff.
- [ ] Implementation PR contains **zero** “proof-only” dumps that belong in evidence (keep tests that *are* product code in implementation).
- [ ] Disposer can replay without the original Agent chat.

## Anti-patterns

- “Works on my machine” with no command, cwd, or SHA.
- Screenshots of the IDE instead of the behavior.
- Evidence files on `feat/` branches.
- Agent self-Accept after pasting logs.
- Storing production secrets in `evidence/`.
