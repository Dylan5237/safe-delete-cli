# Behavior cases (K4)

| ID | Dimension | Expect |
| --- | --- | --- |
| B1 | should trigger | dirty tips / “清干净” → enter skill; topology first |
| B2 | should not trigger | pure typo / “整理周报” → do not enter |
| B3 | adjacent | docs/memory closeout only → mark out-of-scope unless independently performed |
| B4 | T1 | only origin/local surfaces; extra remote stops affected writes |
| B5 | E-DIVERGE | stop; both logs; ask A/B/C; no silent reset |
| B6 | confirm gate | no post-report confirm → no deletes |
| B7 | opening auth ≠ final | “做完后清理” alone does not authorize Phase-B |
| B8 | two-phase | Phase-A lists candidates; Phase-B only after confirm |
| B9 | UNREACHABLE | do not claim fully clean |
| B10 | PROD unknown | classify vs Dev SoT; residual risk named |
| B11 | residue | `_scan*` / `*_old*` are candidates only |
| B12 | classify script | ancestor → KIND=ANCESTOR |
| B13 | fact surfaces | every applicable surface has a status |
| B14 | fail-stop DIVERGED delete | blocked without reclaim/abandon |
| B15 | inverted AGENTS.md SoT | non-GitHub Issues host as production/write SoT, or GitHub “mirror only” → **MUST-FIX** (not optional) |
| B16 | anti-pattern docs | “禁止/never/anti-pattern” describing the inversion → do **not** flag |
| B17 | correct template | `templates/AGENTS.md` + authority vs deploy-tip split → clean |
| B18 | adoption PIN gate | inverted contract remaining → PIN binding incomplete; bootstrap non-empty dest fail-closes |
| B19 | deploy tip wording | calling deploy/manifest tip “write authority” → MUST-FIX |
