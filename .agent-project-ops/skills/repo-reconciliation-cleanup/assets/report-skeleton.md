# Report skeleton (two-phase)

## Phase A — before destructive cleanup

```text
## 对账清理预览（未删）

**拓扑 / SoT**：T? · authority=`…` · PROD=`…|UNKNOWN`

**事实面状态**
- authority tip: …   ← write authority tip (GitHub `origin`)
- unsupported extra remotes / old roles: … | none (preserved, no sync)
- deploy/manifest tip: … | same-as-authority | UNKNOWN  ← **not** write SoT
- AGENTS.md remote contract: clean | **MUST-FIX inverted SoT**
- local/worktrees: …
- open PRs: …
- backlog Issues: …
- residue: …

**分类摘要**：ANCESTOR n · AHEAD n · DIVERGED n · SAME n

**待你确认后才删**
- … (name + KIND + reason)

**无法裁决 / Hold**
- …

**遗留**：pending / UNREACHABLE / dual-tip debt；没有写「无」
```

## Phase B — after confirmed cleanup

```text
## 清场结果

**成功删除**：…
**拦截**（护栏/非 ANCESTOR）：…
**失败**：…
**复盘审计**：inventory 重跑结论
**残留 warning**：…
```
