---
name: git-authority-and-projection
description: >
  Optional second git remote is projection-only (mirror / fast-forward from
  GitHub authority). Use when remotes include more than origin, an internal
  GitLab or other mirror exists, tips diverge, reconciling authority vs
  projection vs an aux repo, aligning protected main, failing closed on
  projection errors, or cleaning cursor/sync branches across remotes.
  Never push topic branches to the projection remote.
---

# git-authority-and-projection (pinned wrapper)

Follow the full pinned skill at [../../../.agent-project-ops/skills/git-authority-and-projection/SKILL.md](../../../.agent-project-ops/skills/git-authority-and-projection/SKILL.md).

Do not invent a parallel process. `.agent-project-ops/PRINCIPLES.md` wins.
