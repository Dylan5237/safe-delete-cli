# 完成回报评论

只复制代码块内正文，替换占位符并按任务验收项增减表格行。绑定最终 HEAD 和 PR，分别列出已验证、失败和未验证；没有证据时不能写通过。偏离合同先停下处理，不靠回报补授权。

这是等待复核的交付，不是验收结论。回报后任务 Issue 保持 verification；普通子任务不直接改变父 Phase 标签。执行者不自行合并、关闭任务或验收；由另一位主 Agent 按实际检查复核。主 Agent 自己实现的任务，仍要等拍板人的最终验收覆盖。

后续关闭按任务类型处理：执行 Agent 实现的 standard 子任务在 PR 合并、非实现者的主 Agent 验收后，移除旧状态、标 `status:done` 并关闭；主 Agent 自己实现的任务、light 任务、Phase 和发布，等拍板人最终验收覆盖后才 done。light 任务等发布最终验收后关闭（不发布的项目等全部已确认目标最终验收）；有授权和原因记录的明确取消也标 done 并关闭。

Phase/发布取消须拍板人明确授权；主 Agent 仅可取消现有规则允许的任务，改变已确认目标仍须按 §11.8 批准。

light 中主 Agent 的技术复核和 PR 合并不构成单独的任务验收；任务验收由拍板人的最终验收覆盖，随后立即 done/关闭，不增加单独的主 Agent 任务验收步骤。

```markdown
<!-- apo-task-completion v1 -->
task: #{{TASK_ISSUE}}
owner: {{AGENT_ID}}
workdir: {{ABSOLUTE_PATH}}
branch: {{BRANCH}}
head: {{FINAL_HEAD_SHA}}
pr: {{PR_URL}}
status: verification

## 实际改动

{{CHANGES_AND_FILES}}

## 验收证据

| 验收项 | 实际结果 | 命令/步骤与证据链接 | 验证状态 |
| --- | --- | --- | --- |
| {{ACCEPTANCE_ITEM}} | {{OBSERVED_RESULT}} | {{EVIDENCE}} | 已验证 / 失败 / 未验证 |

## 失败和未验证

{{FAILED_OR_UNVERIFIED_OR_NONE}}

## 合同偏差与阻塞

{{DEVIATIONS_AND_BLOCKERS_OR_NONE}}

## 下一步

交主 Agent 复核当前 HEAD 的必需检查和证据；本评论不表示任务或 Phase 通过验收。
```
