# Playbook: Git branch and remote / 分支与远端

## Goal

Use GitHub `origin` as the only remote and named topic branches. Additional remotes are unsupported; preserve existing configuration for explicit migration review, never silently remove it or use it to bypass origin.

## Steps

1. Read AGENTS.md and the Command Center. Check `git remote -v` and `.agent-project-ops/remotes` (`authority=origin`). Unknown/extra remotes stop affected writes.
2. Freeze the task contract and major-change check before creating its branch; a hit requires a disposer decision or a named pre-approval.
3. Fetch origin. Resolve the approved origin task base from explicit selection, project configuration or the verified remote default; use [git-worktree.md](git-worktree.md). Do not assume main when the project uses another base.
4. Branch names: `feat|fix|docs|evidence/{issue}-{slug}`. `evidence/` is optional for a proof-only PR; tests and evidence may also accompany the implementation PR or Issue.
5. Push with `git push -u origin HEAD`, open a PR to the project's real default branch, and inspect all current-SHA required CI and review gates before merge. Never push directly to the default branch or rewrite its history.
6. After merge or close run `scripts/tidy-worktrees.sh --apply`. It removes only proven finished work, archives closed-unmerged tips before deletion and keeps uncertainty/local changes. Do not delete by hand. New work starts from the updated authority tip.
7. A long-lived branch, parked work, dirty/ignored contents or unverifiable PR is retained with a reason. Use `--park` / `--abandon` only under the existing retirement contract.

## Done when

- One task = one linked Issue, one branch and one PR.
- Only origin receives pushes, no default-branch direct update.
- Required checks/reviews were verified; evidence maps the frozen tests.
- Retirement summary is recorded; PR merge is not final acceptance.
