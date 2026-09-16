# PRINCIPLES — v0.1.1

These invariants are **binding**. A local Agent that owns a project must load this file with the skills in `skills/` before proposing work. If a playbook step conflicts with an invariant, the invariant wins.

Version: **v0.1.1**  
Scope: Git + GitHub Issues/PRs + local coding Agents. No business domain.

---

## 1. Agent proposes / control plane disposes

本地 Agent 可以起草合同、分支、PR、验收证据，但**不能自行宣布阶段通过或改写已冻结合同**。

- **Propose:** drafts, patches, checklists, evidence packs, exception requests.
- **Dispose:** human (or an explicit control-plane owner named on the Command Center issue) accepts, rejects, or returns.
- An Agent that is “project owner” still **proposes**. Ownership means it keeps the board honest, not that it rubber-stamps itself.

## 2. Chat ≠ state

对话、本地笔记、Agent 记忆**不是**项目状态。

- Canonical state lives in: GitHub Issue bodies + comments, labels, PR descriptions, and commits on named branches.
- If it is not on the Issue/PR/git object, it did not happen.
- Summarize chat decisions **into the Issue** in the same turn they are made.

## 3. PR merge ≠ Phase PASS

合并实现 PR 只表示“代码进入默认集成分支的候选历史”，**不是**阶段验收通过。

- Phase PASS requires: frozen contract still intact, verification evidence reviewed, and an explicit Accept on the Phase issue.
- Merging without Accept leaves the phase in `verification` (or `in-progress`), never `done`.

## 4. Contract Freeze before implementation

每个 Phase 必须先冻结合同（范围、非目标、验收口径、接口/数据契约、风险），再开实现分支。

- Freeze is a dated comment or checklist on the Phase issue, labeled accordingly.
- Changing a frozen field requires an **Architecture Exception** issue, not a quiet chat edit.
- Agents must refuse to start implementation PRs against an unfrozen phase.

## 5. Fail closed

缺证据、缺权限、缺冻结、缺指定 owner 时：**停**，标 `blocked`，写清缺口。禁止“先做了再说”。

- Unknown architecture → Architecture Exception, not a speculative refactor.
- Cannot verify → no PASS proposal.
- Cannot reach `origin` or protected `main` rules → do not invent a second remote as a workaround. A **projection** remote (Principle 10) is not that workaround.

## 6. One phase one core problem

一个 Phase 只解决**一个**核心问题。附属清理必须能在一句话里挂到该问题上，否则另开 Phase。

- Split when: two independent acceptance tests, two owners, or two freeze contracts would be clearer.
- Do not use a Phase as a sprint dump or a product roadmap.

## 7. Methodology never depends on business repos

本仓库是方法论。业务仓库**引用**本仓库的 skills/playbooks，绝不把业务 SOP、产品阶段图、领域模型写进本仓库。

- External product repos may be **linked** from `examples/` as illustrations only.
- Do not vendor business code, env, or domain docs here.
- If a playbook sentence needs a product noun to make sense, rewrite it.

## 8. One worktree ≈ one task ≈ one PR branch

并行工作用 worktree 隔离。每个 worktree 绑定一个 Issue（或 Phase 子任务）和一条 PR 分支。

- Path convention: `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`
- Do not stack unrelated diffs in one worktree.
- Delete or park the worktree when the PR is merged or abandoned.

## 9. Evidence PRs ≠ implementation PRs

实现 PR 改产品/库代码。证据 PR 只提交可复核的验证材料（日志节选、截图路径、测试输出、复现步骤），**不夹带功能改动**。

- Branch prefix `evidence/` is reserved for evidence PRs.
- Mixing them makes Phase Accept unverifiable. Fail closed and split.

## 10. One write authority / 至多一个可写权威

Git **写入权威**只有一个：承载 Issues/PR 的 GitHub 仓库（通常 `origin`）上的约定分支 tip。投影远端（镜像、内部 Git 宿主等）只允许 **读** 或从权威 **快进**；本地与 Cloud Agent 工作区是草稿，不是第三套 SoT。

- Inventing a second source of truth (pushing day-to-day features to the projection, or treating a sandbox `main` as landed history) is forbidden.
- Projection outage or reject → fail closed (stop release); do not retarget workflow to the mirror.
- **PR merge ≠ Phase PASS** remains Principle 3: landing on the authority default branch is not Accept.

Playbooks: `playbooks/git-branch-and-remote.md` (origin-only default), `playbooks/git-authority-and-projection.md` (optional second remote).

---

## Change control

- Invariants are versioned. Breaking changes bump the version in this file and in `README.md`.
- Playbooks may add steps; they may not weaken these ten rules.

### Changelog

- **v0.1.1** — Principle 10: at most one write authority; projection remotes are read-or-FF-from-authority.
