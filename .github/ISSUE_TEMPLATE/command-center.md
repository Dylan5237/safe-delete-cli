---
name: Command Center
about: 项目指挥中心 — single index, roster, and policy for Agent-owned ops
title: "[Command Center] Project control plane"
labels: "type:command-center, status:in-progress"
---

## 目的 / Purpose

Canonical **control plane** for this business repository. Chat is not state. Methodology: https://github.com/Dylan5237/agent-project-ops (`PRINCIPLES.md` v0.1.1).

## Methodology binding

- PIN URL:
- PIN SHA:
- PIN ref/date:
- Root binding files present: yes / no

## Disposer / 拍板人

- Handle:
- May `FREEZE ACK` / `PHASE ACCEPT` / `EXCEPTION ACCEPT`: **yes**
- Distinct GitHub identity from day-to-day Agent credentials?: yes / no / unknown

## Project-ops Agent / 日常 Owner（仍为 propose）

- Agent id:
- GitHub identity used for git/PR operations (if known):
- May push directly to `main`: no
- May self-Accept phases: **no**

## Roster

| Role | Handle / Agent | Notes |
| --- | --- | --- |
| Disposer | | |
| Implementer | | |
| Reviewer | | |

## Git authority / remotes

- Default branch: `main`
- Authority remote: `origin`
- Projection remote(s): `(none)` or names
- `.agent-project-ops/remotes` matches the line above: yes / no / n/a
- Unknown extra remotes: **BLOCKED until classified**
- Branch names: `feat|fix|docs|evidence/{issue}-{slug}`
- Worktrees: `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`
- Direct push to default branch: **forbidden**

## Protection capability

Record what was actually verified, not what was requested:

- Capability: **A / B / C**
  - A = PR + code-owner/independent review gate verified
  - B = PR-only; no independent-human-review guarantee
  - C = unprotected or protection could not be verified → **BLOCKED**
- Force push disabled: yes / no / unknown
- Default-branch deletion disabled: yes / no / unknown
- Notes / plan limitation:

If Agent and disposer use the same GitHub identity, GitHub cannot distinguish human from Agent actions; do not describe CODEOWNERS as a human-vs-Agent security boundary in that configuration.

## Hook state for this clone

- `git config --get core.hooksPath` = `.githooks`: yes / no
- If this was a fresh clone and value was missing, installer run: yes / no / n/a

## Phase index

| Phase issue | Core problem (one sentence) | Status | Result |
| --- | --- | --- | --- |
| # | | backlog | |

## Open exceptions / blocks

| Issue / block | Phase | Status |
| --- | --- | --- |
| | | |

## Adopt notes

- Binding path: root `AGENTS.md` → pinned `.agent-project-ops/PRINCIPLES.md`
- Relevant project skills: `.agents/skills/*/SKILL.md`
- Projection operations require `git-authority-and-projection` before non-origin push.
