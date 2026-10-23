---
name: Command Center
about: 项目总控台，集中查看状态、负责人和决策记录
title: "[Command Center] 项目总控台"
labels: "type:command-center, status:in-progress"
---

## 1. 一眼状态

<!-- 每次门禁变化后，用 project-automation.py status 先预览，核对 plan_id 后 apply 生成第 1 节；详见快照 playbooks/automation.md。无法更新时，在 GitHub 写明阻塞。 -->

| 项目 | 现在 |
| --- | --- |
| **当前工作** | #编号 + 一句话 |
| **状态** | 未开工 / 进行中 / 卡住 / 待验收 / 已完成 |
| **待你决定** | 无，或 `D-n`（类型）+ 链接 |
| **最近完成** | — |
| **卡点** | 无，或缺少什么 |
| **下一步**（只写一件） | |
| **收尾检查** | 最新 `apo-tidy:` 行 |

更新于 YYYY-MM-DD。项目状态应以 Issue、PR 和提交记录为准。

## 项目说明

- 方法论地址：{{METHODOLOGY_URL}}
- PIN 提交：{{METHODOLOGY_SHA}}
- PIN 分支或标签：{{METHODOLOGY_REF}}
- 根目录规则文件是否已接入：是 / 否

## 项目设置

- 流程档位：process_mode={{PROCESS_MODE}}（未记录时按 standard）
- Agent 工具：agent_tools={{AGENT_TOOLS}}
- 外部工具：external_tools={{EXTERNAL_TOOLS}}（none 表示不接入）

## 拍板人

- GitHub 账号：
- 负责事项：大改动开工确认、最终验收和例外
- 与日常 Agent 操作是否使用不同 GitHub 身份：是 / 否 / 未知
- 对固定格式决策请求的回复：`批准 A` / `改用 B` / `退回：<原因>`（适用的旧决定词仍有效）

## 主 Agent

- Agent 标识：
- GitHub 操作账号（如已知）：
- 是否可直接推送默认分支：否
- 必需检查通过后是否可合并任务 PR：是（合并若会发布或部署，仍需满足相应大改动门槛）
- 可验收其他 Agent 完成的任务；不能验收自己的工作或最终验收阶段

## 负责人

| 角色 | 账号或 Agent | 备注 |
| --- | --- | --- |
| 拍板人 | | |
| 主 Agent | | |
| 执行 Agent | | |
| 审查人（可选） | | |

## GitHub 仓库

- GitHub 仓库：
- 默认分支：从真实仓库读取，不要假设为 `main`
- 唯一写入远端：`origin`
- 本地是否存在意外的其他远端：否 / 是（是时先停止写入并查明）
- 是否禁止直接推送默认分支：是
- 分支约定：`feat|fix|docs/{issue}-{slug}`；可选证据 PR 使用 `evidence/{issue}-{slug}`
- 工作区约定：`{repo}/.worktrees/{issue-or-phase}-{owner}-{slug}`

## 分支保护

只记录实际核实到的保护能力：

- 能力：**A / B / C**
  - A = 已核实 PR 和可独立执行的审查或代码所有者门禁
  - B = 已核实必须使用 PR，但不能保证人类身份独立
  - C = 必需的服务端保护不可用或无法核实
- 禁止强推：是 / 否 / 未知
- 禁止删除默认分支：是 / 否 / 未知
- 说明或限制：

如果 Agent 和拍板人使用同一 GitHub 身份，不得把代码所有者规则描述成人机隔离边界。

## 本机 Hook

- `git config --get core.hooksPath` 是否为 `.githooks`：是 / 否
- 若新克隆后缺少设置，是否运行安装脚本：是 / 否 / 不适用

## 阶段索引

| Phase Issue | 核心问题（一句话） | 状态 | 结果 |
| --- | --- | --- | --- |
| # | | backlog | |

## 未解决的例外或阻塞

| Issue / 阻塞 | 对应阶段 | 状态 |
| --- | --- | --- |
| | | |

## 接入记录

- 根规则入口：`AGENTS.md` → 固定版本的 `.agent-project-ops/PRINCIPLES.md`
- 项目 Skills：`.agents/skills/*/SKILL.md`
- 当前规则来源与项目自有要求的差异：

## 证据和验收

- 验收证据可以放在 Phase Issue 或实现 PR；单独证据 PR 可选。
- 阶段最终验收由拍板人完成；CI 通过、审查通过和 PR 合并均不代替最终验收。
