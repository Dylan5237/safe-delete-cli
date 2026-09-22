# safe-delete × Tencent WorkBuddy / CodeBuddy 集成调研

**日期：** 2026-09-22（Asia/Shanghai, CST）  
**范围：** Dylan5237/safe-delete-cli 是否/如何让 WorkBuddy（及同系 CodeBuddy）的文件删除走 trash  
**约束：** 只读调研，未改任何代码  
**读者：** PM + Dylan（简体）

---

## 结论（一句话）

WorkBuddy/CodeBuddy **具备 Claude 兼容的 PreToolUse 拦截能力**（可 deny/改写 Bash 类删除），值得做 **新 selector（`workbuddy` / `codebuddy`）而非复用 `claude`**；但 Dylan 当前是 **原生 Windows**，而 safe-delete **不支持原生 Windows Python（依赖 fcntl）**，且官方对 `~/.workbuddy/settings.json` hooks 的文档仍薄——**应开 P9 为「先 spike 再实现」票，不赞成只做 path-shim，也不赞成直接判 C 放弃。**

**来源标签约定：** 每条关键主张后附 URL，或标 `【无官方来源 / 推断】`。

---

## 推荐方案（A / B / C）

| 选项 | 含义 | 结论 |
| --- | --- | --- |
| **A** path-only（`hook install path-shim`） | 只靠 PATH 拦截 `rm`/`unlink`/`rmdir` | **不推荐作为主路径** |
| **B** 新建 PreToolUse 风格 adapter + selector | 写入 `~/.workbuddy` / `~/.codebuddy` settings，拦截 Bash/execute_command | **推荐（主路径）** |
| **C** 不值得做 | 放弃 WorkBuddy 集成 | **不推荐**（能力存在，但有前置阻塞） |

**推荐：B（带强制 spike 门闩）**  
- Spike 通过后再 Freeze + 实现 + evidence；spike 失败则把 P9 降级为「文档说明 + 建议用 CodeBuddy CLI/WSL」或关闭实现。  
- Path-shim 可作为 **CodeBuddy CLI / WSL 上的纵深防御补充**，不能替代 B。

---

## 证据与摘录（带 URL）

### 1) 产品形态：WorkBuddy 桌面站 vs CodeBuddy 编码 CLI/IDE

> “Tencent WorkBuddy is a full-scenario AI agent desktop workstation… Local File Operations… Batch File Processing”

— https://www.workbuddy.ai/docs/workbuddy/Overview

> “WorkBuddy Configuration Separation: WorkBuddy now uses an independent `.workbuddy/` configuration directory, separated from CLI's `.codebuddy/`”

— https://www.workbuddy.ai/docs/cli/release-notes/v2.48.0

> CodeBuddy 配置目录：`~/.codebuddy`（Windows `%USERPROFILE%\.codebuddy`）；可用 `CODEBUDDY_CONFIG_DIR`；说明可与 WorkBuddy 等共存应用隔离。

— https://www.workbuddy.ai/docs/cli/installation

> 用户现场：skills 在 `~/.workbuddy/skills`（非 `~/.codebuddy/skills`）— **与 v2.48.0 分离一致**。【用户陈述；与官方 release note 互证】

### 2) Hooks：PreToolUse 可在执行前拦截 / deny / 改写

配置路径（**官方文档写的是 CodeBuddy 路径**）：

| Scope | Path |
| --- | --- |
| User | `~/.codebuddy/settings.json` |
| Project | `<repo>/.codebuddy/settings.json` |
| Project local | `<repo>/.codebuddy/settings.local.json` |

— https://www.workbuddy.ai/docs/cli/hooks

> “Runs after CodeBuddy builds tool arguments but before executing the tool.”

> PreToolUse 输出可含 `permissionDecision`: `allow` \| `deny` \| `ask`，以及 `modifiedInput` 改写参数。

> Exit code 2：`PreToolUse` → “Blocks the tool call”.

— https://www.workbuddy.ai/docs/cli/hooks

> “Hooks 钩子系统的 PreToolUse 钩子会在权限弹审批之前运行，可以编程式 allow / deny / 改写输入。”

— https://www.workbuddy.cn/docs/cli/permissions

> IDE Hook 指南明确：**完全兼容 Claude Code Hooks 规范**；matcher 例 `Bash`、`Write|Edit`。

— https://www.codebuddy.ai/docs/ide/Features/hooks （同系镜像：https://www.workbuddy.ai/docs/ide/Features/hooks）

> IDE vs CLI 工具名映射（关键）：CLI `Bash` ↔ IDE `execute_command`；CLI `Write` ↔ IDE `write_to_file`；matcher 可双向别名，但 hook stdin 的 `tool_name` 取决于运行时。

— https://www.codebuddy.ai/docs/ide/Features/hooks 附录 E

> Windows：hooks **强制 Git Bash**（不支持 cmd/PowerShell）；可用 `CODEBUDDY_CODE_GIT_BASH_PATH`。

— https://www.workbuddy.ai/docs/cli/hooks

> Hooks Beta，自 CodeBuddy Code v1.16.0+；API 可能演变。

— https://www.workbuddy.ai/docs/cli/hooks

### 3) `~/.workbuddy/settings.json` —— 官方薄、二手源较一致

**官方：** 仅明确「WorkBuddy 使用独立 `.workbuddy/`」；**未在已抓取的 hooks/settings 正文里把 hooks 路径写成 `~/.workbuddy/settings.json`**（hooks 页仍写 `~/.codebuddy/...`）。  
→ 【官方文档缺口】

**二手（谨慎采用）：**

- rtk PR：写入 `.workbuddy/settings.json` 或 `~/.workbuddy/settings.json`，matcher `Bash|execute_command`。  
  https://github.com/Kayphoon/rtk-tx/pull/2  
  https://github.com/rtk-ai/rtk/pull/2066 （均已 closed，未作为上游事实）
- memorph crate：`~/.workbuddy/settings.json`，事件含 `PreToolUse` 等。  
  https://docs.rs/memorph/latest/src/memorph/providers/workbuddy/hook.rs.html

### 4) safe-delete 现有冻结适配器（只读）

README / hook 安装：

> `safe-delete hook install <claude|cursor|path-shim>`

— https://github.com/Dylan5237/safe-delete-cli/blob/main/README.md

代码（`safe_delete/hook.py`）：

- 选择器仅：`claude` | `cursor` | `path-shim`（别名 `rm-shim`）
- Claude：`~/.claude/settings.json` 或项目 `.claude/settings.json`，`event_key=PreToolUse`，matcher=`Bash`
- Cursor：项目 `.cursor/hooks.json`，`event_key=preToolUse`
- 共享 mode：`pretooluse` 或 `path-shim`；协议 `HOOK_PROTOCOL_VERSION = 1`
- **无 `workbuddy` / `codebuddy` selector**

— https://github.com/Dylan5237/safe-delete-cli/blob/main/safe_delete/hook.py

平台：

> “Native Windows Python is not… storage layer imports `fcntl`… run inside WSL”

— https://github.com/Dylan5237/safe-delete-cli/blob/main/README.md

本地 brief（箱内二次汇总，非厂商原文）：WorkBuddy/CodeBuddy 有 `PreToolUse`/`PostToolUse`；Windows Git Bash；路径偏 `.codebuddy`。  
— `/workspace/skills-usage-telemetry-2026.md`、`/workspace/agent-skills-2026-reference.md`

---

## Q1 — 产品形态与 hooks 能力

### 产品形态

| 产品 | 形态 | 配置根 | 证据 |
| --- | --- | --- | --- |
| **WorkBuddy** | 桌面「职场 Agent」工作站（文档/表格/演示/本地文件批处理） | 自 v2.48.0 起独立 **`.workbuddy/`** | Overview + release notes |
| **CodeBuddy Code** | 编码向 **CLI + IDE（Craft Agent）** | **`.codebuddy/`** / `~/.codebuddy` | settings / codebuddy-dir / installation |

Dylan 使用 `~/.workbuddy/skills` → **更贴近 WorkBuddy 桌面产品线**，不是纯 CodeBuddy CLI 默认布局。【用户 + release note】

### Hooks 能力（可验证部分）

| 问题 | 答案 | 来源 |
| --- | --- | --- |
| 事件名 | 至少含 `PreToolUse`、`PostToolUse`、`SessionStart/End`、`Stop`、`UserPromptSubmit`、`PreCompact` 等（CLI 文档称 27+） | workbuddy.ai hooks |
| 配置文件 | **文档正式路径**：`~/.codebuddy/settings.json`、项目 `.codebuddy/settings*.json`；**WorkBuddy 桌面是否读 `~/.workbuddy/settings.json`：官方 hooks 页未写清** | hooks + installation + release note |
| 能否在执行前拦截 | **能**：PreToolUse 在工具执行前跑 | hooks |
| 能否 deny | **能**：`permissionDecision: "deny"` 或 exit 2 | hooks + permissions 中文页 |
| 能否 rewrite | **能**：`modifiedInput` 改写工具参数（如 Bash `command`） | hooks + IDE hooks 示例 |
| Bash/删除类 | matcher 可对 `Bash`；权限示例含 `Bash(rm:*)` deny；IDE 侧工具名可能是 `execute_command` | hooks / permissions / IDE hooks |
| 热更新 | 改 settings **不热加载**；需 `/hooks` 面板确认或新会话 | hooks |

**不确定点（必须 spike）：** WorkBuddy 桌面是否真的从 `~/.workbuddy/settings.json` 加载与 CodeBuddy 同构的 `hooks.PreToolUse`。【无完整官方文档；二手源声称会】

---

## Q2 — 与现有 `claude` / `cursor` / `path` 差异：能否复用

### 差异表

| 维度 | `claude` | `cursor` | `path-shim` | WorkBuddy（目标） | CodeBuddy CLI（目标） |
| --- | --- | --- | --- | --- | --- |
| Selector | `claude` | `cursor` | `path-shim` / `rm-shim` | **需新：`workbuddy`** | **需新：`codebuddy`**（或与 workbuddy 分路径） |
| 配置文件 | `~/.claude/settings.json` 或 `.claude/settings.json` | `.cursor/hooks.json`（项目） | 无 host JSON；写 package `bin/` | **推断** `~/.workbuddy/settings.json` / `.workbuddy/settings.json` | `~/.codebuddy/settings.json` / `.codebuddy/...` |
| 事件键 | `PreToolUse` | `preToolUse` | n/a | **推断** `PreToolUse`（Claude 兼容） | `PreToolUse`（官方） |
| Matcher / 工具 | `Bash` | Cursor 自有 schema（扁平 `command`） | PATH 上的 `rm`/`unlink`/`rmdir` | **推断** `Bash\|execute_command` | `Bash`（CLI）；IDE 另有 `execute_command` |
| 协议核心 | 共享 `pretooluse` adapter + protocol v1 | 同左 mode，不同 host 注册 | 独立 `path-shim` | **可复用 pretooluse 决策核**；**不可复用 claude 的 config 路径/注册块** | 同左，路径换 `.codebuddy` |
| 已冻结？ | 是 | 是 | 是 | **否** | **否** |

**结论：**

1. **可以复用** adapter-neutral 的 `decide_request(..., adapter="pretooluse")`、payload 生成、fail-closed 语义（现 `hook.py`）。  
2. **不能**把 selector 写成 `claude` 去「顺便」罩住 WorkBuddy——会写错 `~/.claude`，对 Dylan 的 `~/.workbuddy` 无效。  
3. **需要新 selector**（至少一个 `workbuddy`；若同时支持编码 CLI，再建 `codebuddy`，避免把两套配置根搅在一起）。  
4. Host 注册形态可对齐 Claude：`{"matcher":"Bash|execute_command","hooks":[{"type":"command","command":"<payload>"}]}` —— 【CodeBuddy 官方结构 + 二手 WorkBuddy matcher；WorkBuddy matcher 待 spike 确认】。

---

## Q3 — A / B / C 方案证据与风险

### A — path-only（`setup path` / `hook install path-shim`）

**做法：** 安装 PATH shim；指望 WorkBuddy/CodeBuddy 子 shell 走到 shim 的 `rm`。

**证据支持：** path-shim 已有 P4 evidence；对「真的调用了 PATH 上的 `rm`」有效。  
— https://github.com/Dylan5237/safe-delete-cli/blob/main/docs/project/p4-hook-coverage.md  
— evidence `p4-path-shim`

**风险 / 为何不够：**

1. Agent 常用 **Bash 绝对路径** `/bin/rm`、`find -delete`、语言 API、`git clean` —— 明确 **out of coverage**（P4 bypass inventory）。  
2. IDE 文件删除可能走 **Write/Edit/delete 工具**，根本不经过 `rm`。【推断；官方工具表有 Write/Edit，无专用 Delete 名】  
3. WorkBuddy 桌面进程是否把用户 PATH 注入到工具沙箱：**无官方保证**【无来源】。  
4. Dylan **Windows 原生**：safe-delete CLI 本身要 WSL；PATH shim 在 Win32 PATH 与 Git Bash PATH 之间对齐成本高。【README 平台限制】

**定位：** 仅作 CodeBuddy CLI/WSL 的 **可选补充**，不作主交付。

### B — 新 PreToolUse-style adapter（推荐）

**做法：**

1. Spike：在 Dylan 机（或同版本 WorkBuddy）验证  
   - `~/.workbuddy/settings.json` 的 `hooks.PreToolUse` 是否触发  
   - stdin 中 `tool_name` 是 `Bash` 还是 `execute_command`  
   - `modifiedInput` / deny 是否对删除命令生效  
2. Freeze：新增 selector `workbuddy`（± `codebuddy`）、settings 路径、matcher、Windows/WSL 调用约定。  
3. 实现：复用 `pretooluse` payload；注册逻辑仿 `claude`（matcher 数组）；可能需把 shell 命令字符串 tokenize 成 argv（Claude adapter 已有类似路径——以现 hook 输入约定为准）。  
4. Evidence：真实 PreToolUse 向量 → `safe-delete add` → ledger；含 fail-closed。

**证据支持：** CodeBuddy/WorkBuddy 文档族明确 PreToolUse deny/rewrite；IDE 文档称 Claude Hooks 兼容；二手集成已按 `~/.workbuddy` + `Bash|execute_command` 建模。

**风险：**

| 风险 | 严重度 | 缓解 |
| --- | --- | --- |
| `.workbuddy` hooks 官方文档缺口 | 高 | **P9 先 spike**；失败则不实现 |
| Hooks 标 Beta、行为可能变 | 中 | 锁版本；doctor 探测 |
| Windows 无原生 CLI | **阻塞** | 要求 WSL；hook command 调 `wsl.exe ... safe-delete` 或只支持在 WSL 内跑的 CodeBuddy——**需设计进 Freeze**【推断方案】 |
| `modifiedInput` 在多 hook 合并时可能被吞（Claude 系有先例） | 中 | 单 dispatcher hook；测 rewrite | https://github.com/anthropics/claude-code/issues/79321（Claude 先例，非腾讯官方） |
| 非 Bash 删除路径（Write 清空、专用删除工具、MCP） | 中 | 文档写清 out-of-coverage；可选后续 matcher |
| Git Bash 强制 | 低 | payload 用 `python3` 显式调用（官方 tip） |

### C — 不值得做

**反对理由：** 删除安全是 safe-delete 产品目标；宿主已公开 PreToolUse；Dylan 已在用 WorkBuddy。  
**唯一接近 C 的情形：** spike 证明桌面 WorkBuddy **根本不跑 settings hooks**，且用户拒绝 WSL——则实现 ROI 差，可关闭实现票、只写「不支持」说明。

---

## Q4 — 工作量粗估与是否开 P9

### 粗估（Freeze + 实现 + evidence）

| 阶段 | 人日（约） | 备注 |
| --- | --- | --- |
| Spike（真机 hooks + tool_name + deny/rewrite） | 0.5–1 | **门闩**；含 Windows/WSL 可达性 |
| Contract Freeze 增量（selector/路径/matcher/平台） | 0.5 | 不改已冻结 claude/cursor/path 语义 |
| 实现 + 单测（仿 claude 注册 + 新 selector） | 1–2 | 复用 pretooluse 核 |
| Evidence（直播/录屏或脚本 + ledger） | 0.5–1 | 对齐 P4 风格 |
| **合计（spike 绿）** | **约 3–5** | |
| Spike 红 → 收尾文档 | 0.5 | 不开实现或关闭 P9 |

### 是否开 P9？

**建议开 P9，但标题/范围写成：**

> **P9: WorkBuddy/CodeBuddy PreToolUse adapter — Spike → Freeze → Implement（gated）**

验收门闩建议：

1. Spike 证明：在目标产品上 PreToolUse 对删除类命令可 deny 或 rewrite 到 `safe-delete add`（附 settings 路径截图/文件 + 一次成功 trash 证据）。  
2. 明确平台：WSL-only 或「hook → wsl」方案写入 Freeze；**不承诺原生 Win32 Python**。  
3. 实现后：`hook install workbuddy`（± `codebuddy`）+ status/doctor + 至少一组 P4 风格 evidence。  
4. 若 spike 失败：P9 关闭或转为「Won't fix / document-only」，不硬做。

**不建议**开一张「直接实现、无 spike」的大票。

---

## 缺口 / 风险（汇总）

1. **官方未完整文档化** WorkBuddy 桌面 hooks 的 settings 路径（仅有 `.workbuddy/` 分离说明）。  
2. **safe-delete 不支持原生 Windows**；Dylan 主机为 Windows —— 集成前必须解决运行时（WSL）。  
3. IDE `execute_command` vs CLI `Bash` 双名；matcher 需覆盖。  
4. Hooks Beta；改写语义需单 hook、实测。  
5. Path-shim / PreToolUse 都无法覆盖语言 API、`find -delete`、绝对路径 rm 等（与现有 bypass inventory 一致）。  
6. 二手源（rtk / memorph）一致性高但 **非腾讯官方**，只能指导 spike，不能当 Freeze 唯一依据。

---

## 给 PM 的回复格式（可直接转发）

**一句话结论：** WorkBuddy/CodeBuddy 有 Claude 式 PreToolUse（可拦/改 Bash 删除），应做新 selector，而非只靠 path；但 Windows 原生 + `.workbuddy` 文档缺口要求先 spike。  

**推荐选项：** **B**（新 PreToolUse adapter：`workbuddy`/`codebuddy`），path 仅作可选补充；**开 P9（gated spike）**。  

**证据链接：**

- https://www.workbuddy.ai/docs/cli/hooks  
- https://www.workbuddy.ai/docs/cli/release-notes/v2.48.0  
- https://www.workbuddy.cn/docs/cli/permissions  
- https://www.codebuddy.ai/docs/ide/Features/hooks  
- https://github.com/Dylan5237/safe-delete-cli/blob/main/README.md  
- https://github.com/Dylan5237/safe-delete-cli/blob/main/safe_delete/hook.py  

---

## Sources list

### 官方 / 一手

1. https://www.workbuddy.ai/docs/workbuddy/Overview — WorkBuddy 产品形态  
2. https://www.workbuddy.ai/docs/cli/hooks — Hooks 参考（PreToolUse、settings 路径、modifiedInput、exit 2、Windows Git Bash）  
3. https://www.workbuddy.ai/docs/cli/settings — settings.json / hooks 键  
4. https://www.workbuddy.ai/docs/cli/codebuddy-dir — `~/.codebuddy` 布局  
5. https://www.workbuddy.ai/docs/cli/installation — 配置目录与 `CODEBUDDY_CONFIG_DIR`  
6. https://www.workbuddy.ai/docs/cli/release-notes/v2.48.0 — WorkBuddy `.workbuddy/` 与 CLI `.codebuddy/` 分离  
7. https://www.workbuddy.cn/docs/cli/permissions — PreToolUse 在权限链阶段 0；deny/改写  
8. https://www.workbuddy.cn/docs/cli/hooks — 中文 hooks  
9. https://www.codebuddy.ai/docs/ide/Features/hooks — IDE Hook 指南；Claude 兼容；Bash↔execute_command  
10. https://www.workbuddy.ai/docs/ide/Features/hooks — 同上镜像  
11. https://www.workbuddy.ai/docs/cli/hooks-guide — Hooks 入门  

### safe-delete 仓库（只读）

12. https://github.com/Dylan5237/safe-delete-cli — 仓库  
13. https://github.com/Dylan5237/safe-delete-cli/blob/main/README.md — 安装选择器、Windows/WSL  
14. https://github.com/Dylan5237/safe-delete-cli/blob/main/safe_delete/hook.py — selectors / 注册  
15. https://github.com/Dylan5237/safe-delete-cli/blob/main/docs/architecture/freeze.md — 钩子边界契约  
16. https://github.com/Dylan5237/safe-delete-cli/blob/main/docs/project/p4-hook-coverage.md — 覆盖与 bypass  
17. https://github.com/Dylan5237/safe-delete-cli/blob/main/evidence/p6/hooks.md — P4 evidence  

### 二手 / 社区（降权）

18. https://github.com/Kayphoon/rtk-tx/pull/2 — WorkBuddy settings + `Bash|execute_command`  
19. https://github.com/rtk-ai/rtk/pull/2066 — 同上（closed）  
20. https://docs.rs/memorph/latest/src/memorph/providers/workbuddy/hook.rs.html — `~/.workbuddy/settings.json`  
21. https://github.com/anthropics/claude-code/issues/79321 — Claude `updatedInput` 合并问题（类比风险，非腾讯）  

### 箱内 brief（非厂商）

22. `/workspace/agent-skills-2026-reference.md` — WorkBuddy/CodeBuddy skills 路径汇总  
23. `/workspace/skills-usage-telemetry-2026.md` — WorkBuddy hooks/telemetry 笔记  

### 用户陈述（非网页）

24. Dylan：Windows hostname `ROGStrix37`；skills 于 `~/.workbuddy/skills`  

---

*报告结束。未修改 safe-delete-cli 或任何产品代码。*
