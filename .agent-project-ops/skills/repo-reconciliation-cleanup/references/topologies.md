# Topologies / 支持边界

先只读识别拓扑，在对账 Issue 记录 ID。支持的远端只有 GitHub origin。

| ID | Signals | Surfaces / action |
| --- | --- | --- |
| T0 | no remote or unreachable origin | local inventory only; no remote deletion or completed binding claim |
| T1 | local clone + only GitHub origin | local + authority; origin/default is write SoT |
| T2 | historical extra-role configuration | unsupported; preserve settings and stop affected writes for migration review |
| T3 | GitHub repository without usable local clone | remote read-only inventory; local surface not applicable |
| T4 | unknown extra remote or multiple write-looking hosts | unsupported; stop cleanup, never choose a new write authority implicitly |

Only T0/T1/T3 have a current workflow. Old topology IDs remain identifiable for reporting, not for synchronizing another host. Declaring an extra remote in an old registry does not make it supported. Add-origin or migration needs its own confirmed scope.
