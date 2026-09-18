# P7 Adversarial Review — CLI-first slice (agent docs + install UX + doctor + purge hardening)

- Reviewer: Kimi Code k3(adversarial product/architecture review,pre-freeze proposal 阶段)
- Baseline: `main @ bf9d21e`(P0–P6 Sol-accepted);本评审不构成 Phase Freeze / PASS / FREEZE ACK,也不主张 merge 权限
- 评审方式:全部结论均在 `/workspace/safe-delete-cli` 上用 `bf9d21e` 实际命令/代码复核过;区分为「已验证事实(含复现)」与「风险判断」
- 范围纪律:不重新打开 P0–P6 已接受契约;Exception #12 保持 P2-only 残留,不在本 slice 扩展或"修复"威胁模型

## 1. Verdict: **REQUEST_CHANGES**

理由一句话:提案方向(CLI-first、不做 App、agent 文档化)是对的,但「one-shot install」「doctor green ⇒ safe」「agent 会遵守 purge 纪律」三个核心假设在当前 `bf9d21e` 上有**已复现的反例**(默认路径下 `hook install` 直接 fail-closed 拒绝安装;多项目 Cursor 第二次安装静默 no-op),且 slice 把纯文档与需要 freeze 的新 CLI 面(`doctor`、purge 便捷旗标、平台预检)混在一起,必须先拆开。

## 2. Executive summary(≤10 行)

1. 提案可取:CLI-first、observability 留在 `list/show/hook status`、明确拒绝 GUI,符合已冻结契约。
2. **致命反例 A**:在全新默认环境(不设 `SAFE_DELETE_ROOT`/`XDG_DATA_HOME`)下,`./safe-delete hook install claude` 以 exit 2 `path_forbidden` 失败——包目录默认与存储根同为 `~/.local/share/safe-delete`,被 `_reject_storage_namespace` 自锁。「一键安装」在默认机器上今天就不成立。
3. **致命反例 B**:多项目 Cursor 下,第二次 `hook install cursor`(在新项目 cwd)返回 `ok:true, changed:false`,实际仍写入**第一个**项目的 `hooks.json`,新项目完全没有 hook——用户以为已保护,实际裸奔。
4. **反例 C**:安装的 hook payload 硬编码 `sys.path.insert(0, "/workspace/safe-delete-cli")` 且 `cli_path` 钉在开发 checkout;checkout 移动/清理后 hook 全部 fail-closed 拒绝删除,用户困惑。
5. WSL-only 是真约束(`fcntl` + `O_NOFOLLOW`/`O_DIRECTORY`),但代码没有任何平台预检:原生 Windows Python 上连 `version` 都是 `ModuleNotFoundError: fcntl` 堆栈。
6. purge 语义本身稳(`--execute` 无 `--yes` 拒绝、`0d` 拒绝、预览为默认),但「purge 到现在所有 eligible」没有安全拼写;`--before <未来时间戳>` 合法且会清掉 0 秒前刚删的条目——文档必须直面。
7. `hook status` 已存在且诚实(带 `out_of_coverage` 清单);**`doctor` 和顶层 `status` 在 `bf9d21e` 不存在**,提案不得把它们写成已发货。
8. 任何 `doctor`/新旗标/安装修复都是产品代码变更,按仓库方法论需要独立 Issue + Freeze;本 slice 应先做 docs-only,代码项另开 P7 契约提案。
9. 文档必须逐字保住 P4 bypass 清单,并把 Exception #12 残留风险贴在所有 restore/doctor 相关陈述旁。

## 3. Assumption kills — 假设 → 具体反例

| 提案假设 | 反例(均已验证或可直接复核) |
| --- | --- |
| 「one-shot install」 | 默认环境下 `./safe-delete hook install claude` → exit 2,`{"code":"path_forbidden","message":"hook management path is inside safe-delete storage: .../.local/share/safe-delete"}`。根因:包根 `xdg_data_home()/safe-delete`(`hook.py:469`)与默认存储根(`storage.py:54-72`)相同,`_reject_storage_namespace`(`hook.py:792-806`)把所有管理路径(含包根本身)判为位于存储命名空间内。测试从未暴露:`tests/test_hook_enforcement.py:53-58` 每次都把 `XDG_DATA_HOME` 与 `SAFE_DELETE_ROOT` 设成**不同**目录。契约 `freeze.md:743` 本身就把 payload 放在 `$XDG_DATA_HOME/safe-delete/hooks/`,与守卫实现相互矛盾——契约与实现必有一个要改。 |
| 「agent 会读 AGENTS.md 并遵守 purge 安全」 | 反例不需要假设 agent 恶意:只要 skill 写一句「purge 用 `--execute --yes`」,cron 与 agent 都会照抄;而 `--before 2099-01-01T00:00:00Z --execute --yes` 是**合法**调用,实测把 0 秒前 `add` 的条目物理清除。 obedience 不是安全边界,旗标语义才是;文档不能把确认旗标教成肌肉记忆。 |
| 「doctor green ⇒ 删除安全」 | 反例 B(上表第 2 行):projA 安装后,`hook status` 对 cursor 报 `enforced:true`,而 projB 完全没有 hook。status 绿只证明「已登记的那个 (host, config_path) 边界」成立,证明不了「你当前打开的项目」被覆盖。 |
| 「WSL runtime + Windows Cursor host 无缝」 | hook 请求 `cwd` 必须是绝对、规范化的 POSIX 路径(`hook.py:285-287`);Windows 侧 `C:\...` 或 `\\wsl$\...` 形态的 cwd 会被 deny(fail-closed 是好的,但表现为「Cursor 里每次 rm 都被拒」)。安装的 payload 是 `#!/usr/bin/env python3` + POSIX 绝对路径,Windows 原生 Cursor 根本无法执行该 hook command。两者叠加:这不是「无缝」,是「仅在 Cursor 的 shell 实际运行于 WSL 内时可用」。 |
| 「默认 30d 对 cron 作者和 agent 都能被正确理解」 | 阈值优先级是 `--older-than/--before` → `SAFE_DELETE_RETENTION_DAYS` → 30d(`retention.py:181-272`)。agent 会话里 export 了 `SAFE_DELETE_RETENTION_DAYS=7`,cron 环境没有 → 两套阈值同时生效,且互不可见。干跑 JSON 里的 `policy.source` 已暴露来源(实测 `"source":"default"`),文档必须教双方**先跑预览、读 `source`/`cutoff` 再决定**。 |
| 「store 路径同义词不会分叉 ledger」 | `resolve_root` 只 realpath 同一目录的别名(`storage.py:72`);`~/.local/share/safe-delete` 与「在该规范名后追加 `-store` 后缀」的口误变体是两个独立 ledger 宇宙。README 从未写出完整默认路径名(只说 `$XDG_DATA_HOME/safe-delete` 兜底链),用户机器上已出现 paraphrase——文档必须钉死唯一规范名。 |
| 「install 写好宿主配置即完成」 | path-shim 的 install 只返回 `path_activation: "prepend ... to PATH"` 提示(契约禁止改 shell 启动文件);cursor 默认写到 **cwd 的** `.cursor/hooks.json`(`hook.py:904-905`)——在错误目录执行即静默装错项目。「one-shot」对两种宿主都不成立。 |

## 4. WSL/Windows split — 风险 + 必须的文档/CLI 诚实

1. **平台预检缺失(产品代码,freeze-gated)**:`storage.py:7` 顶层 `import fcntl`,`open_directory_without_symlinks` 还要求 `O_NOFOLLOW`/`O_DIRECTORY`(`storage.py:96-103`)。原生 Windows Python 下任何子命令(含 `version`)都是 `ModuleNotFoundError: No module named 'fcntl'` 堆栈——noisy 但不可行动。本 slice 至少要在文档写死:「仅支持 Linux/macOS/WSL;原生 Windows 出现 `fcntl` ImportError 即走错了解释器」。把堆栈换成一行明确报错属于产品改动,应进入后面的 P7 契约提案(`safe_delete/cli.py:main` 或 `__main__.py` 加 preflight)。
2. **路径三种形态必须各有一句真话**:`/home/<u>/proj`(WSL native,受支持)、`/mnt/c/...`(DrvFs;与 WSL home 的默认 root **跨设备**,`add` 会被 `cross_device` 拒绝;若把 root 也放到 `/mnt/c`,9P/DrvFs 上 `fcntl flock` 语义未经任何证据验证——文档必须标「/mnt/* 工作区为未验证配置,doctor/status 不得声称 enforced」)、`\\wsl$\...`(Windows 侧视角,hook 协议直接 deny,见 §3)。
3. **Cursor 在 Windows、项目在 WSL**:唯一受支持形态是「Cursor 的集成终端/agent shell 跑在 WSL 内」。文档要给判定方法(在 Cursor 终端里 `uname`/`which python3`)和反例症状(hook command 无法执行/全 deny)。`wsl.exe -e safe-delete list` 这类 Windows→WSL 观察桥只能作为「待验证 recipe」标注,不得写成受支持路径。
4. **ledger 对 Windows 工具不可见**:ledger 在 WSL home 内;Windows 侧资源管理器/工具看不到(或只能经 `\\wsl$` 读)。observability 承诺必须限定为「在 WSL 内运行 `list/show`」。
5. **项目根检测跨 OS 边界**:`_nearest_supported_project_root` 与 hook `cwd` 都是 POSIX 语义;文档禁止暗示能识别 Windows 侧项目根。

## 5. Purge footgun 分析(只给建议,不实现)

已验证的当前行为(`bf9d21e`):

- 默认 = 预览(`"mode":"dry_run"`),物理删除必须 `--execute --yes`;`--execute` 缺 `--yes` → exit 2;`--dry-run` + `--execute` → exit 2。
- `--older-than 0d` → `usage_error`(语法强制正整数,设计正确);`--before now` → `usage_error`(必须 RFC3339 带时区)。
- `--before <未来 RFC3339>` **合法**,实测清掉刚 `add` 的条目。
- 崩溃恢复候选(`purge_pending` + 末事件 `purge_intent`)**不看当前 cutoff**(`retention.py:332-346` 注释明确「recovery does not use the current policy cutoff」)——这是有意设计,文档必须解释,否则用户会以为 `--older-than 30d` 能拦住它。

建议(文档层立即可做;旗标层需 freeze):

1. 「purge 到现在所有 eligible」的唯一安全拼写写成文档 recipe:`safe-delete purge --before "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --execute --yes --json`,并配一句「`--before` 接受未来时间戳,届时**全部** active 条目都 eligible——这是 wipe-all 语义,不是笔误兜底」。
2. 文档固定三步纪律:先预览 `--json` → 读 `policy.source`/`cutoff`/`candidates` → 才追加 `--execute --yes`。任何 agent 文档**禁止**出现「总是加 `--execute --yes`」。
3. 若想提供更清晰的子命令/旗标(如 `purge --all-eligible` 或 `--before now` 语法糖),列为后续 P7+ 契约提案项;本 slice 不私自加产品旗标。
4. 时区:retention 锚点是 UTC `Z`(`retention.py:161-166`),cron 本地时区不影响比较,但 `--before` 必须带 `Z` 或偏移——文档给出正反例各一。
5. cron 示例必须带显式环境:`SAFE_DELETE_ROOT=...` 与绝对 CLI 路径,并说明 cron 环境与交互 shell 的差异会静默改变 root 与阈值来源。README 现有的 `0 2 * * * /usr/bin/safe-delete ...` 还有第二个坑:仓库发货形态是依赖相邻 `safe_delete/` 包的 `./safe-delete` 脚本,拷到 `/usr/bin` 单独存在即坏。

## 6. Install / doctor 诚实边界

`bf9d21e` 已存在:`hook install|status|disable|uninstall`,`hook status`(无参)输出三个 selector 的全量 JSON,含 `out_of_coverage` 十条清单与「未证明即未 enforced」的告警文案(`hook.py:1198-1252`)。**不存在**顶层 `status` 或 `doctor`。

doctor(若做)可以声称:
- 聚合只读检查:`hook status` 三边界 + 存储根可写 + 平台预检(fcntl/O_NOFOLLOW 可用)+ payload 源路径仍存在 + `cli_path` 不是 world-writable。
- 逐边界输出 enforced/not-enforced,并**原样携带** `out_of_coverage` 清单。
- 对 PATH shim:只能说「**当前进程 PATH** 中 shim 优先」(`_path_precedence`,`hook.py:1064-1082` 只看本进程环境),不得声称未来 shell/其它工具不会重排。

doctor 必须拒绝声称:
- 拦截了 PowerShell / `os.unlink` / `/bin/rm` / `find -delete` / `git clean` / busybox / 包装器(`sudo`/`env`/`sh -c`)/ 未配置 agent / 人类进程。
- 覆盖了「当前打开的项目」——只能覆盖「已登记的 config_path」;多项目 Cursor 必须逐项目列出。
- Windows 宿主上的任何 enforcement。
- Exception #12 残留已修复(见 §8)。
- 「storage usable ⇒ 删除安全」——usable 只是可写性。

另外两条 install 诚实义务:
- `--cli` 覆盖只校验「可执行」(`hook.py:628-664`),world-writable 脚本也会被钉进 registry(B5 修复后路由坚持用安装时登记的 CLI——防 shadowing 是对的,但也意味着安装时给的坏路径被忠实固化)。install 应拒绝或至少告警 world-writable CLI;doctor 必须检查。
- `uninstall` 只清**登记在案**的那个 config_path;多项目场景下别的项目残留的 `preToolUse` 条目指向已删除的 adapter payload(见 §3 反例 B)——文档要写明该限制,实现修复进 P7 提案。

## 7. Bypass inventory — agent 文档必须包含的陈述

与 `docs/project/p4-hook-coverage.md` 和 `hook.py:49-60` 的十条逐字对齐,不得软化、不得缩写为「大部分删除被拦截」:

1. Python/Go/Node 等语言文件 API(如 `os.unlink`)不经过 hook。
2. `find -delete` 不在覆盖内。
3. `git clean` 不在覆盖内。
4. `busybox rm` 不在覆盖内。
5. 绝对路径 `/bin/rm`、`/bin/unlink`、`/bin/rmdir` 不在覆盖内。
6. 其它未配置的 agent/工具不在覆盖内。
7. 无 hook 的容器/命名空间不在覆盖内。
8. 特权进程与人类进程不在覆盖内。
9. PATH 重排后 shim 失效。
10. disabled/uninstalled 状态下裸 `rm` 在边界之外。

另需补一句提案点名要求的:Windows 侧 PowerShell(`Remove-Item` 等)天然在边界外——本产品今天根本不在原生 Windows 运行。agent 文档推荐写法是「受支持边界 = 已登记的 PreToolUse(claude/cursor)+ PATH shim 三者;其余一律视为未覆盖」,并给每条配一行 P4 回放证据链接。

## 8. Exception #12 — 保持残留,明确非目标

- 本 slice **不**触碰 same-UID staging publication 威胁模型;`docs/architecture/exceptions.md` 原文不动。
- agent 文档/restore 说明/doctor 输出涉及 restore 时,必须附残留提示:「Exception #12 — P2-only same-UID staging publication — excluded model / residual risk; not fixed」(对齐 `evidence/p6/README.md:68-70` 的既有措辞)。
- doctor **不得**设置任何会被理解为「#12 已修复」的绿色检查项。
- 建议:在 P7 契约提案 Issue 里显式登记「#12 后续硬化阶段」为候选后续 phase(独立 Issue、独立 freeze),本 slice 只登记、不实施。

## 9. Scope creep / App 拒绝清单

本 slice 一旦出现以下内容,一律拒绝并回指本清单:

- 任何 GUI/Electron/tray/web dashboard/通知中心——包括「先写个只读 web viewer」。
- 「App 级 observability」话术:进度页、仪表盘、实时刷新。`list --json` + `hook status --json` 就是上限。
- 自动调度器安装(cron/systemd 写入)——契约明确 operator-owned(`freeze.md:840-843`)。
- 为「体验一致」移植原生 Win32 运行时(msvcrt 锁等)——这是新平台契约,不是 UX 修补。
- 把 doctor 长成配置中心(自动改 PATH、自动修 hooks.json 之外的东西)。
- 修改 `.agents/skills/` 下的方法论 pin(AGENTS.md 核心规则 7:业务 SOP 不回灌方法论快照)。agent 使用文档应落在 `docs/project/` 或仓库根的独立产品文档,不进方法论 skill 目录。

## 10. Must-fix(任何本 slice implement/freeze 的阻塞项)

1. **默认路径下 hook install 自锁** — 问题:包根与默认存储根同为 `~/.local/share/safe-delete`,`hook install` 在全新机器上 exit 2 `path_forbidden`(§3 反例 A)。伤害:「一键安装」在真实默认环境 100% 失败。建议:改 `safe_delete/hook.py::_reject_storage_namespace`,保留对 `trash/`、`ledger.jsonl`、`locks/` 的禁止,允许包目录 `hooks/`、`bin/` 与存储根同居(契约 `freeze.md:743` 本来就这么写);或把包默认位置移出存储根并同步改契约——二选一,必须连同 `tests/test_hook_enforcement.py` 新增「默认环境(不设 SAFE_DELETE_ROOT/XDG_DATA_HOME)安装成功」用例,例如 `test_default_paths_hook_install_succeeds`。
2. **多项目 Cursor 静默 no-op** — 问题:registry 按 selector 单条(`integrations["cursor"]`),第二次在不同 cwd 安装返回 `ok:true, changed:false` 且仍写第一个项目(§3 反例 B)。伤害:用户以为新项目已保护,实际零覆盖,`hook status` 还是绿的。建议:`hook_install` 在已存在 registry 条目且本次解析出的 `config_path` 与登记不一致时 fail-closed(`usage_error`,提示显式 `--project`/`--config` 或先 uninstall);或把 registry 键改为 `(selector, config_path)`。文档同时写明「cursor 安装是按项目的,每个项目一次显式安装」。位置:`safe_delete/hook.py::hook_install`/`_registry_entry_matches`;测试:`test_cursor_second_project_install_requires_explicit_target`。
3. **payload 硬编码开发 checkout** — 问题:安装的 adapter/shim 是 `sys.path.insert(0, "<checkout>")` + `cli_path=<checkout>/safe-delete`(实测写入 `/workspace/safe-delete-cli`)。伤害:checkout 移动/清理后所有删除被 fail-closed 拒绝,用户无从下手;`status` 虽能报 `adapter_runnable:false`,但 install 时没有任何「这是开发 checkout,勿当生产安装」的提示。建议:文档写死「安装前先把仓库放到稳定位置」;doctor/安装结果增加「payload source 位于 git checkout」告警;长期方案(vendored 单文件 payload)进 P7 提案。位置:`safe_delete/hook.py::_payload_text`、`docs/` 安装章节。
4. **平台预检缺失** — 问题:原生 Windows 上连 `version` 都是 `fcntl` ImportError 堆栈(§4.1)。伤害:用户分不清「装错了」还是「产品坏了」。建议:文档本 slice 写死 WSL/Linux/macOS-only 与症状表;代码 preflight(`safe_delete/cli.py:main` 开头 try import fcntl → 一行 `unsupported platform: requires Linux/macOS/WSL (fcntl)` 并 exit 2)列入 P7 契约提案。
5. **唯一规范 store 路径名** — 问题:README 只有兜底链表达式,用户侧已出现「规范名后追加 `-store` 后缀」的口误;不同 root = 不同 ledger 宇宙,且 cron/交互环境分叉(§3 末行)。伤害:agent 删进 A root、人在 B root 里 `list` 为空,判定「数据丢失」。建议:README 与新 agent 文档第一句钉死 `~/.local/share/safe-delete`(及 `$XDG_DATA_HOME`/`$SAFE_DELETE_ROOT` 优先级),显式声明「规范名加 `-store` 后缀的变体不是本产品的路径」;`./safe-delete doctor`/`hook status` 输出已解析 root 供核对。
6. **purge「到现在全部 eligible」缺安全拼写 + `--before` 未来时间戳 = wipe-all** — 问题见 §5。伤害:agent/cron 作者用最直觉的方式(`--before now` 报错后改填未来时间)反而达成最大破坏。建议:文档 recipe + 警告(本 slice);是否加糖旗标留 P7 提案;agent 文档禁止「总是 `--execute --yes`」。
7. **doctor 不得发明已发货** — 问题:`bf9d21e` 没有 `doctor`/顶层 `status`;提案叙述把它们当既有能力。伤害:文档谎言直接摧毁信任链。建议:docs 全部区分「当前行为(`hook status`)」与「提案(`doctor`)」;`doctor` 作为新子命令属产品代码,先开 P7 freeze Issue 再实现;本 docs slice 只承诺 `hook status`。
8. **agent 文档落点与 purge 纪律** — 问题:现 `AGENTS.md` 是纯 ops 绑定,无产品使用指引;若把 purge 用法写进方法论 skill 目录会违反 ops 规则 7,若写成「`--execute --yes` 标配」则制造系统性误删。建议:新建 `docs/project/p7-agent-usage.md`(或等价产品文档),含:`add`/`list`/`show`/`restore`/`purge` 用法与 `--json` 可拷示例、purge 三步纪律、§7 十条 bypass 逐字、WSL-only 与路径形态表、规范 store 路径、`hook status` 解读。
9. **Cursor 宿主 schema 未经真实宿主验证** — 问题:写入的 `.cursor/hooks.json` 为 `{"hooks":{"preToolUse":[{"command":...}]}}`,P6 证据全部是合成协议 payload + Claude 风格配置(`evidence/p6/hooks.md` 自承 "Claude-style PreToolUse adapter"),没有真实 Cursor 会话证据。伤害:「cursor 一键装」可能装进一个 Cursor 根本不读的字段。建议:docs 标注「Cursor 集成已在协议层验证,真实宿主回放为 P7 证据缺口」;P7 证据任务:在真实 Cursor(WSL 项目)回放 PreToolUse 触发并记录 artifact。
10. **install  PATH 激活与 `--cli` 信任的诚实标注** — 问题:path-shim 安装不碰 PATH(契约如此),`--cli` 接受任意可执行路径。伤害:用户装完 shim 以为已生效;坏 CLI 被固化。建议:文档给出确切 `export PATH=...` 行与「shell 配置/其它工具可能后序重排,用 `hook status` 复核当前进程 PATH」;install 对 world-writable `--cli` 拒绝或告警(代码项进 P7 提案)。

## 11. Should-fix(非阻塞但强烈建议)

- `hook status`/未来 doctor 的 humans 输出给「(host, project/config_path) 覆盖矩阵」视图,直接暴露「哪个项目没被盖」。
- README cron 行改为带显式 `SAFE_DELETE_ROOT` 与仓库内绝对路径的完整示例,或给出「安装到稳定位置后再配 cron」的先后顺序。
- `management_selectors()` 同时广告 `path-shim`/`rm-shim` 别名(`hook.py:1553-1556`);文档统一用 `path-shim`,别名一句话带过。
- claude user-global(`~/.claude/settings.json`)与 cursor project-local 的语义差异要有对照表;混装时 `hook status` 三行各说各话,文档教用户逐行读。
- 文档建议但不强制:agent 调 `purge` 前先把 `SAFE_DELETE_RETENTION_DAYS` 的当前值打进日志(dry-run JSON 的 `policy.source` 已有,引用即可)。
- 未来 P7 提案考虑 `purge --before now` 语法糖 + 执行回显「本次物理删除 N 个条目」到 stderr 的强制摘要(现在 JSON 有,人类模式不明显)。
- `restore` 文档补一句「destination 已被占用 = exit 3 `destination_exists`,不覆盖」——agent 最需要的行为承诺。

## 12. Nits

- purge JSON 同时输出 `cutoff` 与 `cutoff_utc` 同值字段(`retention.py:274-285`),无害但文档只引用一个,避免读者找差异。
- `hook status` 在 storage 未 init 时 `usable:false` + `storage_unavailable`,行为正确;文档给一张「该状态 = 先跑 `init`」的对照即可(已实测 exit 0、ok:true)。
- README 说「Phase 2 uses only the Python standard library」——已是全产品事实,措辞更新为现在时。
- `_print_human` 的 list/show 人类输出未在本次攻击面内详查;若 P7 提「human-friendly list/show」,验收标准写成「人能在 5 秒内指出 entry_id 与 original_path」这类可操作语句。
- 文档中出现的示例 entry_id 用冻结契约里的 `550e8400-...` 风格占位,别用真实机器上的 UUID(避免读者误当证据)。

## 13. IMPLEMENTATION CONTRACT — 给下一轮 Claude Code 的执行契约

定位:**这是提案工作,不是 Phase Freeze**。在 `@Dylan5237` 对 P7 契约提案做出 FREEZE ACK 之前,只允许 docs-only 变更;任何 `safe_delete/` 产品代码改动(包括 doctor、平台预检、install 修复)都必须先走独立 Issue + Freeze。Merge ≠ Phase PASS。

有序任务:

1. **(docs)** 新建 `docs/project/p7-agent-usage.md`:§10.8 全部内容 + §7 十条 bypass 逐字 + §4 WSL 路径形态表 + §5 purge 三步纪律与 `--before` wipe-all 警告 + 唯一规范 store 路径声明。验收:文档内每条 CLI 示例在 `bf9d21e` 上可原样运行(在临时 `SAFE_DELETE_ROOT` 下逐条执行过);每一条「当前不支持」陈述与 `./safe-delete --help` 输出一致。
2. **(docs)** 修订 `README.md`:钉死默认 root 全名与优先级链;加「Linux/macOS/WSL only;原生 Windows 报 `fcntl` 即错误解释器」;cron 示例带显式 `SAFE_DELETE_ROOT` 并注明 CLI 需连同 `safe_delete/` 包一起位于稳定路径;明示「安装 cron 是 operator 责任」保持不变。验收:`README.md` 与 `docs/` 中「规范名后追加 `-store` 后缀」的变体字面串必须为零(以该字面串 grep 为证);示例命令在干净环境重放通过。
3. **(docs)** 新建/更新 `docs/project/p7-install-notes.md`:如实记录反例 A/B/C(默认路径自锁、多项目 no-op、checkout 依赖)为**已知限制 + 变通**(`hook install --config/--project` 显式指定、安装前固定仓库位置),不得写成已修复。验收:每条限制附一条今天的实际命令输出摘录。
4. **(control plane)** 开 P7 契约提案 Issue(冻结对象:`doctor` 子命令语义与禁止声称清单、默认路径 install 修复方案二选一、多项目 registry 键设计、平台预检、world-writable `--cli` 策略、`--before now` 语法糖取舍、真实 Cursor 宿主证据任务、Exception #12 后续硬化 phase 的登记)。验收:Issue 引用本评审文件路径与 §10 编号;打 `status:proposed` 之类既有标签约定;不附实现分支。
5. **(docs)** `docs/project/commit-plan.md` 追加 P7 段落骨架(仅提案:docs 三条 + 未来 `feat:` 占位,标注「待 FREEZE ACK」)。验收:不新增任何被暗示已批准的 `feat/` 条目。
6. **(禁止项)** 不改 `safe_delete/` 任何 `.py`;不改 `docs/architecture/freeze.md`/`exceptions.md` 语义(链接级引用允许);不动 `.agents/skills/`;不开 `feat/` 分支;不在 Issue 上自封 `FREEZE ACK`/`PHASE ACCEPT`。

显式 out-of-scope:GUI/tray/web;Win32 原生运行时;调度器自动安装;跨文件系统 copy 兜底;ledger compaction;Exception #12 修复;对 P0–P6 已接受契约的任何重谈。

—

Reviewed by **Kimi Code k3** against `main @ bf9d21e`. All "已验证" statements were reproduced with live commands on 2026-09-18 in disposable `HOME`/`XDG_*`/`SAFE_DELETE_ROOT` sandboxes; no production paths or credentials touched.
