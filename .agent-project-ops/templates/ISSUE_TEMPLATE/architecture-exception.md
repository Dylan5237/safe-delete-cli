---
name: Architecture Exception
about: 已冻结合同需要改变、超出批准范围或放宽验收标准时使用
title: "[Exception] "
labels: "type:exception, status:backlog"
---

## 对应阶段

- Phase Issue：
- 冻结评论链接和日期：

## 为什么不能按原合同继续

<!-- 说明缺少的信息、规则冲突、不安全假设或被阻塞的外部条件。 -->

## 当前已冻结内容

```text

```

## 建议调整后的内容

```text

```

## 对进行中工作的影响

- 需要关闭或改目标的 PR：
- 需要处理的工作区：
- 是否更适合另开阶段：是 / 否

## 决策

按 `.agent-project-ops/templates/decision-request.md`（方法论仓库中为 `templates/decision-request.md`）在本 Issue 发布 `例外` 决策请求。拍板人可回复：

- [ ] `批准 A`（旧回复 `EXCEPTION ACCEPT` 仍有效）：按批准内容重新冻结 Phase 合同
- [ ] `改用 B`：按选择调整，再重新冻结合同
- [ ] `退回：<原因>`（旧回复 `EXCEPTION REJECT` 仍有效）：保持原合同

Agent 只提出方案，不替拍板人回复。
