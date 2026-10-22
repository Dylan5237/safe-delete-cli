# PRINCIPLES — v0.3.0

These invariants are **binding**. A local Agent that owns a project must load this file with the skills in `skills/` before proposing work. If a playbook step conflicts with an invariant, the invariant wins.

Version: **v0.3.0**  
Scope: Git + GitHub Issues/PRs + local coding Agents. No business domain.

---

## 0. Three layers and two process modes / 三层规则与两个流程档位

规则分三层：底线谁都不能关；项目设置由拍板人在初始化时选；每次改动由主 Agent 对照大改动清单判断。

| Layer | Contents | Who changes it |
| --- | --- | --- |
| **Fixed floor / 固定底线** | GitHub `origin` is the only write authority; no direct push to the default branch; one task = one branch = one PR; state lives on GitHub; anything on the major-change list (§11) waits for the disposer; final acceptance is the disposer's; status and decision requests use the fixed formats (§12) | Nobody. These are not project settings. |
| **Project settings / 项目设置** | process mode, Agent tools, external tools | The disposer chooses them at initialization. Changing them later edits `.agent-project-ops/`, so it is §11 item 7 (an Agent proposes; the change lands through a normal PR). `process_mode` is recorded in `.agent-project-ops/project-config`; all three are listed on the Command Center. |
| **Per-change judgment / 每次判断** | Does this change hit §11? | The lead Agent, item by item. Unsure = hit. |

Process modes (`process_mode=light|standard`):

- **`light` / 轻量** — personal small tools. No Phase issues: work moves task by task and each task issue carries its own contract. Final acceptance happens once before each release, in the same request as the release confirmation; a project that never releases gets it when all confirmed goals are done.
- **`standard` / 标准** — long-lived projects maintained by several Agents. Work is grouped into Phases; final acceptance at the end of every Phase.
- The mode decides only how often final acceptance happens and whether Phases are used. The fixed floor and the major-change list are identical in both modes.
- No recorded mode = `standard`.

## 1. The disposer decides three things; the lead Agent decides the rest / 拍板人只管三件事

需要人拍板的只有三类：命中大改动清单（§11）的开工确认、最终验收、例外。其余由主 Agent 决定并记录在 GitHub。任何 Agent 都不能验收自己的工作。

- **Disposer / 拍板人** — the human named on the Command Center. Decides only: (1) start confirmation for work that hits §11, (2) final acceptance (§3), (3) exceptions to a confirmed contract (§4). Nothing else is sent to the disposer.
- **Lead Agent / 主 Agent** — splits work into tasks, dispatches them, reviews task PRs and merges them once the required checks pass, accepts tasks implemented by other Agents, handles blocks, retires branches and keeps the board honest. It prepares every request to the disposer in the fixed format (§12) and never answers one itself.
- **Executing Agent / 执行 Agent** — implements one task on one branch/PR and reports back. It never accepts its own task.
- No Agent accepts its own work. A task the lead Agent implemented itself stays in `status:verification` until the disposer's final acceptance covers it.
- Being the “project owner” does not make an Agent the disposer. An Agent never writes a disposer decision, in any wording.

## 2. Chat ≠ state

对话、本地笔记、Agent 记忆**不是**项目状态。

- Canonical state lives in: GitHub Issue bodies + comments, labels, PR descriptions, and commits on named branches.
- If it is not on the Issue/PR/git object, it did not happen.
- Summarize chat decisions **into the Issue** in the same turn they are made.
- Command Center **section 1** is the one-glance Agents keep current on every gate flip (skill duty; see `skills/github-multi-agent-project-ops`). Chat pings are not a substitute.

## 3. PR merge ≠ Phase PASS

合并 PR 只表示代码进入默认分支，**不是**验收通过。只有拍板人的最终验收才算 PASS。

- PASS requires: the frozen contract still intact, evidence mapped to every acceptance test, and the disposer's final acceptance (§12 type `最终验收`; the legacy reply `PHASE ACCEPT` still counts).
- When: `standard` — at the end of each Phase; `light` — before each release, in the same request as the release confirmation (or when all confirmed goals are done, if the project does not release).
- The lead Agent's acceptance of a task closes that task; it is never a Phase or release PASS.
- Merging without final acceptance leaves a Phase in `verification`, never `done`; in `light`, nothing is released without it.
- If merging into the default branch publishes or deploys in this project, the merge itself is §11 item 4.

## 4. Contract Freeze before implementation

每个 Phase（轻量档：每个任务）先写合同（范围、非目标、验收口径、接口/数据契约、风险）并对照大改动清单检查。命中的，等拍板人开工确认（也可以是之前某次开工确认里写明的提前批准）；没命中的，主 Agent 冻结合同后直接开工。

- Freeze = a dated `CONTRACT FREEZE <date>` comment on the Phase/task issue with the frozen bullets (or a permalink) and one line: `大改动检查：无` or `大改动检查：命中第 N 条（…）`.
- Hit (or unsure) → start confirmation request (§12, type `开工确认`). Implementation begins only after the disposer approves it (`批准 A`; the legacy `FREEZE ACK` still counts). The approval covers the listed items inside the frozen scope; a new hit found later needs its own request.
- **Pre-approval (提前批准).** A start confirmation may also pre-approve later Phases of a written plan: the chosen option must name those Phases, and the request must link the plan. Each such Phase still freezes its own contract with `大改动检查：命中第 N 条，已由 D-n 提前批准`, and starts without a new request only while that contract stays inside the plan as written. Anything the plan does not describe, or the request excluded, needs its own request; final acceptance is never pre-approved.
- No hit → the lead Agent's `CONTRACT FREEZE` is the go-ahead. Nobody waits for a human.
- The lead Agent re-checks §11 whenever it dispatches a task or the planned change grows.
- Changing a frozen contract so that it hits §11, goes beyond the confirmed goal, or removes or loosens a confirmed acceptance test → exception request (§12, type `例外`). Other edits (clarifying wording, splitting into tasks, adding tests) → a new `CONTRACT FREEZE` with a one-line diff note. Never quietly edit a frozen contract.
- Agents refuse to start implementation PRs without a freeze, or with a hit that has no approved request.

## 5. Fail closed

缺证据、缺权限、缺合同、缺指定 owner 时：**停**，标 `blocked`，写清缺口。禁止“先做了再说”。

- Unknown architecture → exception request (§12), not a speculative refactor.
- Waiting for a disposer reply is not `blocked`: only the work that request covers waits (it keeps its status label; the request is listed under “待你决定” on Command Center §1), and unaffected tasks keep moving.
- Cannot verify → no PASS proposal.
- Cannot reach `origin` or protected `main` rules → do not invent a second remote as a workaround. Non-origin remotes are unsupported (Principle 10).

## 6. One phase one core problem

一个 Phase（轻量档：一个任务）只解决**一个**核心问题。附属清理必须能在一句话里挂到该问题上，否则另开 Phase。

- Split when: two independent acceptance tests, two owners, or two freeze contracts would be clearer.
- Do not use a Phase as a sprint dump or a product roadmap.

## 7. Methodology never depends on business repos

本仓库是方法论。业务仓库**引用**本仓库的 skills/playbooks，绝不把业务 SOP、产品阶段图、领域模型写进本仓库。

- External product repos may be **linked** from `examples/` as illustrations only.
- Do not vendor business code, env, or domain docs here.
- If a playbook sentence needs a product noun to make sense, rewrite it.

## 8. One worktree ≈ one task ≈ one PR branch

并行工作用 worktree 隔离。每个 worktree 绑定一个 Issue（或 Phase 子任务）和一条 PR 分支。只有一个任务在做时，空闲的主检出直接承载这条任务分支，不另建文件夹。收尾由脚本自动完成，不靠记性。

- Path convention: `{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`; at most `max_worktrees` task folders at once (default 3; `0` = unlimited).
- Do not stack unrelated diffs in one worktree.
- Retire with `tidy-worktrees.sh --apply` after every merge, before every new task (built into `new-worktree.sh`) and before every final-acceptance request. Retire only what is proven landed (a merged PR whose head contains the local tip, or an upstream deleted after landing); never uncommitted or unmerged work.
- Abandoned work (PR closed unmerged, or `--abandon` decided by the lead Agent — by the disposer when dropping it changes a confirmed goal, §11 item 8) is pushed as tag `archive/<branch>-<sha7>` before its branch is deleted. Deleting an archived branch is not deleting unmerged work.
- Park = commit + push, then `tidy-worktrees.sh --park <branch>`: the folder goes, the branch stays.

## 9. Evidence follows the acceptance tests / 证据对应验收标准

证据可以放在实现 PR 或 Issue 中，不要求单独开分支或 PR。必须说明每项验收标准如何复验，不得用测试通过代替人的最终验收。

- Put tests, fixtures, concise proof excerpts and evidence links in the task PR or Issue.
- A separate evidence PR is **optional** when artifact size or independent verification makes it useful. The `evidence/` prefix remains available for that purpose; it is not a mandatory second PR.
- Never add unrelated feature work under an evidence-only label. Redact secrets and keep proof replayable from the frozen acceptance tests.

## 10. GitHub origin only / 只写 GitHub 主仓

GitHub `origin` 是唯一支持的远端和写入权威。任务分支和 PR 都围绕它推进；本地工作区是草稿，不能替代远端项目状态。

- Push only to `origin`; never push directly to the default branch after repository initialization.
- Additional remotes and legacy remote-role settings are unsupported. Stop affected writes; preserve the old configuration for an explicit migration review, never silently remove it or use it as a fallback.
- An unavailable authority is a blocker, not permission to invent another write target.
- Release/deployment identity is separate from write authority. This methodology currently supplies no second-host publishing channel. Any later publishing channel requires its own confirmed scope (§11 item 4).
- **PR merge ≠ Phase PASS** remains Principle 3. See [git-branch-and-remote](playbooks/git-branch-and-remote.md).

## 11. Major-change list / 大改动清单

命中下面任何一条，先发开工确认，等拍板人回复再动手（§4）。没命中的由主 Agent 自己决定。两个档位用同一份清单。

1. 改架构或对外接口（模块边界，以及别人依赖的 API、命令行、配置或文件格式）
2. 改数据库结构、做数据迁移或删除数据
3. 涉及账号、密钥、权限、支付或隐私
4. 发布、部署或推送到内网 GitLab
5. 强推、改写历史、删除 main 或还没合并的分支（已推送存档标签 `archive/<branch>-<sha7>` 的分支，删除时不算“还没合并”）
6. 引入付费服务或重要新依赖（新框架、新运行时、新外部服务，或会进入发布产物的库）
7. 修改 APO 规则本身（本文件、playbooks、skills、templates 和脚本强制的行为；在业务项目里包括升级或修改 `.agent-project-ops/` 和 AGENTS.md 里的规则）
8. 超出已确认目标的范围（包括扩大范围，或删减、放宽已确认的验收标准）

Applying the list:

- Unsure → treat it as a hit.
- Decisions that are ready at the same time go out as **one** request (§12), never one by one.
- While a request is pending, only the work it covers waits; everything else keeps moving.
- An approval covers exactly what the request listed and grants nothing more.
- Final acceptance (§3) and exceptions (§4) always go to the disposer, list or not.

## 12. Fixed formats for decisions and status / 决策和状态用固定格式

APO 对人只输出两种东西：固定格式的状态，和固定格式的决策请求。

- **Decision request:** every request to the disposer uses `templates/decision-request.md` (bound projects: `.agent-project-ops/templates/decision-request.md`). A request is formal only when the first line of an Issue/PR body or comment is its `<!-- apo-decision v1 | … -->` marker; markers inside code blocks or quotes are examples.
- **Reply:** `批准 A` / `改用 B` / `退回：<原因>`. Legacy words keep their meaning: `FREEZE ACK` approves a start confirmation; `PHASE ACCEPT` / `PHASE RETURN` approve / return a final acceptance; `EXCEPTION ACCEPT` / `EXCEPTION REJECT` approve / return an exception.
- **Revisions:** a changed request is re-posted with the same `id` and the next `rev`; earlier revisions are void and replies to them do not count.
- **Record:** after the reply the Agent posts an `apo-decision-result` marker in the same thread (a reply given in chat is quoted verbatim in the same turn, §2) and links it from every target. The link is a reference, not a signature on the disposer's behalf.
- **Batching:** one request may cover several targets (`target: #a #b`) or several numbered decisions; one reply settles all of them.
- **Status:** Command Center §1 is the status format — its fixed fields, including “待你决定” (pending requests). Status reports reuse those fields plus the latest `apo-tidy:` line; no free-form status essays.

## 13. Write for the reader / 按读者写

给人看的写中文、先说结论、少用术语；给 Agent 看的保持技术写法。

- **For the human** (README, getting started, upgrade notes, Issue templates, status, decision requests): Chinese; the first sentence is the conclusion; avoid jargon, and explain an unavoidable term in plain words the first time it appears; say what the reader has to do, if anything.
- **For Agents** (AGENTS.md, skills, playbooks, scripts): precise technical wording; identifiers, labels and commands stay unchanged.

---

## Change control

- Invariants are versioned. Breaking changes bump the version in this file and in `README.md`.
- Playbooks may add steps; they may not weaken these rules.
- Changing this file, the playbooks, skills, templates or script-enforced behaviour is §11 item 7 and needs the disposer's start confirmation.

### Changelog

- **v0.3.0** — GitHub origin is the only supported remote; remove multi-remote/export workflows and unused Agent adapters; evidence may accompany the implementation PR or Issue. Historical records and legacy upgrade descriptors remain evidence, not current capabilities. Package release is separate.

- **v0.2.0** — §0: three layers (fixed floor / project settings / per-change judgment) and two process modes (`light`, `standard`; unrecorded = `standard`). §1: the disposer decides only start confirmations for major changes, final acceptance and exceptions; the lead Agent decides everything else; no Agent accepts its own work. §3/§4: final acceptance per Phase (`standard`) or per release (`light`); every freeze carries a major-change check and waits for a human only on a hit; a start confirmation may pre-approve later Phases of a linked plan. §8: abandoning is a lead-Agent decision unless it changes a confirmed goal. New §11 major-change list, §12 fixed decision and status formats (`templates/decision-request.md`), §13 writing rules.
- **v0.1.3** — Principle 8: automatic retirement (after merge, before each new task, before Accept); idle primary checkout hosts a single task; task-folder cap; archive-before-delete for abandoned branches; park = push + remove folder.
- **v0.1.2** — Principle 10: export is a third remote role (authority − strip list), not a second write authority.
- **v0.1.1** — Principle 10: at most one write authority; projection remotes are read-or-FF-from-authority.
