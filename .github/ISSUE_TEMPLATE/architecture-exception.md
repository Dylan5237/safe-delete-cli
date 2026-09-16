---
name: Architecture Exception
about: 已冻结合同必须变更时使用 — fail closed, do not quiet-edit the Phase
title: "[Exception] "
labels: "type:exception, status:backlog"
---

## Linked Phase

- Phase issue #:
- Freeze comment URL / date:

## Why fail closed / 为何不能继续实现

<!-- Missing knowledge, contradiction, unsafe assumption, blocked integration, etc. -->

## Frozen text (current)

```text

```

## Proposed text (new freeze)

```text

```

## Impact on in-flight work

- PRs to close / retarget:
- Worktrees:
- Split into a new Phase instead?: yes / no

## Decision

- [ ] Disposer `EXCEPTION ACCEPT` + new `CONTRACT FREEZE` on the Phase
- [ ] Disposer `EXCEPTION REJECT` — keep original freeze

Agent proposes only. Do not self-Accept.
