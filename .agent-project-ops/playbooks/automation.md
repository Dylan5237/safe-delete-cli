# 自动化：预览、核对、再写入

以下命令在项目根目录执行。方法论仓库自身使用 `scripts/`；生成项目使用 `.agent-project-ops/scripts/`。需要 Python 3；GitHub 命令还需要 Git Bash/bash 和已认证的 `gh`。脚本不批准决策、不派发 Agent，也不替代主 Agent 的证据判断。

## 总控台第 1 节

```bash
python3 .agent-project-ops/scripts/project-automation.py status --cc 10 --phase 123 \
  --recent 'PR 链接及已完成的检查' --blocker '无' \
  --next-action '只写一个下一步' --tidy 'apo-tidy: 实际收尾结果'
# 核对生成表格，再用相同参数加上：
# --apply --expect-plan <预览输出的 plan_id>
```

先改真实 Phase/任务状态标签、登记索引和正式决策/结果，再生成表格；不要先把 CC 写成未来状态。指定任务必须存在于 CC 的阶段索引/阶段记录中。状态来自 Issue 的唯一状态标签与开关状态；待决项来自目标 Issue 和 CC 正文/全部评论中，第一行的正式决策标记（只算指定目标的最新 revision，旧版结果不结清新版）。结果必须记录在请求所在的同一讨论；其他目标上的同编号结果/引用不能结清它。正式请求应发在目标 Issue 或 CC；放在其他 Issue 的历史请求先按决策修订流程迁移，不能复制同编号标记冒充新请求。单纯引用链接不会被当成请求。脚本不推断 PASS。

最近完成、卡点、唯一下一步和最新收尾行由主 Agent 从当前 GitHub/提交证据核对后提供。默认仅打印表格和计划摘要，不写 GitHub。确认参数表示已核对该计划；任何读取的控制面记录变化，旧摘要失效。apply 再读一次，只 PATCH 第 1 节，回读核对；其余正文保持原样。GitHub 正文 PATCH 不提供事务式条件写入，仍有并发窗口；多人同时维护 CC 时先协调。写入结果未知时先读 GitHub，不盲目重试。

评论及引用原话中的 Agent/机器人提及改写为“at 名称”，并注明引文已安全改写；避免意外触发机器人。人类拍板人身份和文件导入语法保持原样。

## 派发前文件检查

任务单的 `apo-file-scope v1` 块是允许改动范围的可执行声明，与冻结合同一致。只使用 repo 相对 POSIX 路径；`file:` 表示单文件，`dir:` 表示整棵目录。禁止绝对路径、反斜线、`.`/`..`、通配符和重复项。

```text
<!-- apo-file-scope v1 -->
file: src/session.py
dir: tests/session/
<!-- /apo-file-scope -->
```

```bash
python3 .agent-project-ops/scripts/project-automation.py dispatch-check --task 124
# 同批派发一次传入全部候选：--task 124 --task 125
```

脚本读取 origin 对应仓库的候选任务与所有开放任务，要求状态唯一且合法；候选仅允许 backlog 或 in-progress（开工前检查/运行中复查）。同批候选两两比较，再与其他 `type:task` / `status:in-progress` 任务跨 Phase 比较声明路径，按不区分大小写的保守规则检查。返回 0 = 声明范围无冲突；3 = 已列出重叠任务/路径，先串行或调整冻结范围再派发；2 = 缺范围、状态/格式非法、权限/API 不可用等未知，停止受影响派发。目录按路径分段匹配，`src/auth/` 不会匹配 `src/auth-old/`。

检查只读，不分配 owner、不启动 Agent、不更改 Issue；它不是锁，也不能发现未申报的写入。主 Agent 应在真正 START 前立即重查，同批候选必须在同一命令里全部传入，并在任务范围改变时重查。只读评审不申报为并行实现任务。

## 同步所选宿主技能副本

```bash
python3 .agent-project-ops/scripts/project-settings.py sync-skills --root .
# 核对新增、修改、多余文件列表，再使用同一命令加上：
# --apply --expect-plan <预览输出的 plan_id>
```

`.agents/skills/` 是正本。命令只同步项目已选的 `.claude/skills/` 和 `.codebuddy/skills/`；两者都选时一次同步两者，不创建未选目录、不修改设置、正本或根规则。差异列出文件内容变化、空目录和 POSIX 权限（含可执行位）变化及将移入备份的多余目标文件；摘要绑定项目路径、设置与全部源/目标内容及目录布局。过期摘要、链接/junction、特殊文件或不合法布局拒绝写入。

apply 先准备新树，再把旧目录整体移到 Git 私有目录的 `apo-skill-sync/<id>/`，最后交换新树；目标多余内容可从备份恢复，不永久删除。失败时尝试恢复已交换目录，并输出恢复目录；`manifest.json` 在交换前记录编号备份、目标、暂存路径和进度。手动恢复时先把当前目标移到别处保留，再把对应编号备份移回原目标；原目标不存在的项恢复为不存在。若进程在 `swapping` 状态中断，先查看 target/saved/staging 哪些实际存在：saved 存在则保全当前 target 后恢复 saved；saved 不存在且 existed=true 时原树应仍在 target，不要拿 staging 覆盖；existed=false 时保全新 target 并恢复为不存在。若跨卷移动失败或恢复也失败，保留所有工件，依据 manifest 人工恢复，不继续推送。重复预览应无差异，然后运行 `project-settings.py check`。

## 推送与收尾

推送检查从 origin 实时读取默认 HEAD，不使用本地陈旧指针或 `APO_DEFAULT_BRANCH` 覆盖。网络失败、已有分支但 HEAD 不明时拒绝。空仓首推必须显式设置 `APO_INITIAL_BRANCH`，仅允许创建该分支（不同时推标签）；bootstrap 自动向首次创建命令传递实际本地初始分支。这不是日常推送的绕过开关。

`tidy-worktrees.sh --apply` 切回主线后只做快进更新。失败会返回非零、在 `apo-tidy` 中计入 failed，并保留任务分支/提交；先核对主线分叉或工作区原因，不 reset 或自动合并来绕过。可用相同命令在问题解决后重试。
