# 标签说明

以下标签用于 GitHub 仓库。标签名称是系统标识，保持英文；含义和说明使用中文。可通过 GitHub 页面创建，也可执行本文件末尾的 `gh` 命令。

不要在方法论仓库创建业务领域标签。业务仓库可以增加自己的标签，但不能替换本清单中的状态标签。

## 状态标签（每个 Issue 选一个）

| 名称 | 颜色建议 | 含义 |
| --- | --- | --- |
| `status:backlog` | `BFD4F2` | 尚未派发 |
| `status:in-progress` | `FBCA04` | 已明确负责人、工作区和分支 |
| `status:blocked` | `D93F0B` | 有缺口，暂停受影响的工作并在 Issue 说明 |
| `status:verification` | `5319E7` | 等待证据核对或最终验收 |
| `status:done` | `0E8A16` | 执行 Agent 实现的 standard 子任务的 PR 合并且由非实现者的主 Agent 验收；主 Agent 自己实现的任务、light 任务、Phase 或发布已被拍板人最终验收覆盖；或已明确取消。移除旧状态后标此标签并关闭；light 任务等发布最终验收后关闭（不发布的项目等全部已确认目标最终验收）。Phase/发布取消须拍板人明确授权；主 Agent 仅可取消现有规则允许的任务，改变已确认目标仍须按 §11.8 批准 |

## Issue 类型

| 名称 | 颜色 | 含义 |
| --- | --- | --- |
| `type:command-center` | `1D76DB` | 项目总控台 |
| `type:phase` | `0052CC` | 解决一个核心问题的阶段 |
| `type:task` | `006B75` | 标准档的阶段子任务，或轻量档的独立任务 |
| `type:exception` | `B60205` | 已冻结合同的例外申请 |
| `type:docs` | `C5DEF5` | 文档改动事项 |

## PR 类型

| 名称 | 颜色 | 含义 |
| --- | --- | --- |
| `pr:implementation` | `0E8A16` | 实现、测试或正常文档改动 |
| `pr:evidence` | `5319E7` | 可选的独立验证材料 PR；不要求每个阶段创建 |

## 可选流程标签

这些标签不能替代 Issue 状态：

| 名称 | 含义 |
| --- | --- |
| `freeze:pending` | 合同尚未冻结，或开工确认待回复 |
| `freeze:acked` | 合同已冻结；命中大改动清单时已获开工批准 |
| `accept:proposed` | 已提交最终验收请求 |
| `accept:returned` | 拍板人已退回验收 |

## 创建标签示例

```bash
gh label create "status:backlog" --color BFD4F2 --description "尚未派发"
gh label create "status:in-progress" --color FBCA04 --description "进行中"
gh label create "status:blocked" --color D93F0B --description "存在阻塞"
gh label create "status:verification" --color 5319E7 --description "等待证据或验收"
gh label create "status:done" --color 0E8A16 --description "已完成或取消"
gh label create "type:command-center" --color 1D76DB --description "项目总控台"
gh label create "type:phase" --color 0052CC --description "阶段"
gh label create "type:task" --color 006B75 --description "子任务"
gh label create "type:exception" --color B60205 --description "例外申请"
gh label create "type:docs" --color C5DEF5 --description "文档事项"
gh label create "pr:implementation" --color 0E8A16 --description "实现 PR"
gh label create "pr:evidence" --color 5319E7 --description "可选证据 PR"
```
