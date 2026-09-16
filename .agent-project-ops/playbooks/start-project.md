# Playbook: Start project / 启动项目

## Goal

Stand up a **control plane** in the **business** git repository so a local Agent can own day-to-day ops without treating chat as state.

## When

- A repo was just created by `bootstrap-project`.
- A business repo already exists and is adopting `agent-project-ops`.
- The repository has no Command Center yet.

## Preconditions

- You can create Issues and labels on the business repo.
- GitHub is the write authority (`origin`).
- `PRINCIPLES.md` v0.1.1 is in force, either from a pinned `.agent-project-ops/` snapshot or an explicitly loaded methodology checkout.
- If the repo was bootstrapped, `.agent-project-ops/PIN` contains a real methodology SHA and `.agent-project-ops/remotes` is the remote registry.

## Steps

1. **Load the binding.** Prefer root `AGENTS.md` in a bootstrapped repo, then read `.agent-project-ops/PRINCIPLES.md`. For manual adoption, explicitly load this methodology. Confirm: Chat ≠ state; Agent proposes / control plane disposes; merge ≠ Phase PASS.
2. **Fresh-clone hook check.** Run `git config --get core.hooksPath`. A clone does not inherit this local config. In a bootstrapped repo, if it is not `.githooks`, run `bash .agent-project-ops/scripts/install-hooks.sh`. Missing client hook is not permission to push `main`.
3. **Create labels.** Apply `templates/labels.md` (or the pinned snapshot copy) without inventing overlapping status names.
4. **Verify `main` protection.** Require pull requests and disable force/deletion as hosting capability permits. Record observed capability on Command Center: **A** code-owner review enforced, **B** PR-only, or **C** unprotected/BLOCKED. Never call B an independent-human-review gate.
5. **Open the Command Center issue.** Use `templates/ISSUE_TEMPLATE/command-center.md`. Fill disposer, PIN, default branch, protection capability, Agent roster, and Freeze/Accept policy.
6. **Reconcile remotes.** `git remote -v` must match the registered classification. Default is `origin` only. If a projection is required, it remains mirror/FF only and `git-authority-and-projection` applies before any non-origin push. Unknown remotes → Blocked.
7. **Open Phase-0/Phase-1.** One core problem only. Use the Phase template with backlog status.
8. **Do not implement yet.** Run Freeze on that Phase before any `feat/` / `fix/` branch.

## Done when

- [ ] Command Center exists as the single project index and names the disposer.
- [ ] Status labels exist.
- [ ] `git config --get core.hooksPath` is `.githooks` for this clone when the tracked hook exists.
- [ ] Command Center records protection capability A/B/C; capability C is explicitly Blocked.
- [ ] Command Center records authority/projection and matches `.agent-project-ops/remotes` when present.
- [ ] At least one Phase issue exists with one core problem and no implementation before Freeze.
- [ ] Agent can find the pinned/current playbooks without the original bootstrap chat.

## Anti-patterns

- Treating the methodology repository as the product repository.
- Treating a tracked hook file as proof `core.hooksPath` is active after clone.
- Calling PR-only protection “human approval enforced” when Agent and disposer share an identity.
- Skipping Command Center and tracking work only in chat.
- Pushing “just this once” to `main`.
- Adding a second write authority or using projection as a fallback.
- Embedding business SOP into this methodology repository.
