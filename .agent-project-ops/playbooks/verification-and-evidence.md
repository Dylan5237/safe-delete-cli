# Playbook: Verification and evidence / 验证与证据

## Goal

Make final acceptance replayable from frozen tests. Evidence may live in the implementation PR or Issue; a separate evidence PR is optional. Load [PRINCIPLES.md](../PRINCIPLES.md) §3, §9 and §12 first.

## Steps

1. Map each frozen acceptance test to the actual command, exit status, source SHA and proof link. Tests/fixtures and concise log excerpts may accompany implementation code. Redact secrets.
2. Label the Phase `status:verification` and update Command Center **section 1**. [ ] **CC §1 updated**
3. Use Issue/PR comments or attachments for large/binary evidence. Do not publish secrets or unrelated feature changes under an evidence-only label. Use `evidence/{issue}-{slug}` and the evidence PR template only when a separate PR is useful.
4. Publish **one** formal final-acceptance request using [templates/decision-request.md](../templates/decision-request.md). Its `apo-decision` marker must be the first line; include the acceptance table, known limitations, 1–2 replay steps and the latest `apo-tidy:` line. `EVIDENCE READY` is an evidence report, not a replacement for this request.
5. Only the disposer's reply (`批准 A`, `改用 B`, `退回：<原因>`; legacy `PHASE ACCEPT` / `PHASE RETURN`) determines final acceptance. Record the reply with `apo-decision-result` and reference every target.
6. Missing proof means blocked or verification, never done. PR merge, CI and the Agent's own judgment do not replace acceptance. Update CC §1 on each gate flip.

## Evidence table

| Frozen acceptance test | Actual result | Replay/evidence link | Limitations |
| --- | --- | --- | --- |
| … | … | … | … |

## Done when

- Every frozen acceptance test has replayable evidence.
- The latest formal request and the actual disposer reply are linked.
- Sensitive information is redacted and CC §1 reflects the gate.
