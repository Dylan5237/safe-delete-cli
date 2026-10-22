---
name: repo-reconciliation-cleanup
description: >
  对脏 Git 仓做安全对账与清理：先识别拓扑（仅本地 / GitHub+本地 / 仅远程 /
  不支持的额外远端），钉 Dev SoT 与可选 PROD 地板，只读盘点并给事实面状态，用确定性脚本把
  枝/worktree 分成 SAME·ANCESTOR·AHEAD·DIVERGED，出具预览报告，经处置人看完报告后
  确认再删/回收/放弃，最后复盘审计。在 tip 混乱、陈旧枝、多余 worktree、本地与远程
  完全分叉、会话残留文件、或用户说「有多脏」「今天清干净」时使用。不做产品功能；
  不做文档/规则/记忆知识收尾；无「看完报告后的确认」不删枝。
  PR 合并/关闭后的日常收尾由 tidy-worktrees.sh 自动完成，不需要本技能。
---

# repo-reconciliation-cleanup (pinned wrapper)

Follow the full pinned skill at [../../../.agent-project-ops/skills/repo-reconciliation-cleanup/SKILL.md](../../../.agent-project-ops/skills/repo-reconciliation-cleanup/SKILL.md).

Do not invent a parallel process. `.agent-project-ops/PRINCIPLES.md` wins.
