# Playbook: Start project / 启动项目

## Goal

Stand up a **control plane** in the **business** git repository so a local Agent can own day-to-day ops without treating chat as state.

## When

- A repo was just created by `bootstrap-project`.
- A business repo already exists and **already completed** [adopt-existing-project.md](./adopt-existing-project.md) step 1 (local `AGENTS.md` remote contract rewritten; inverted SoT fail-closed). Adoption is not this playbook.
- The repository has no Command Center yet.

## Preconditions

- You can create Issues and labels on the business repo.
- GitHub is the write authority (`origin`).
- `PRINCIPLES.md` v0.3.0 is in force, either from a pinned `.agent-project-ops/` snapshot or an explicitly loaded methodology checkout.
- If the repo was bootstrapped, `.agent-project-ops/PIN` contains a real methodology SHA and `.agent-project-ops/remotes` is the remote registry.

## Steps

1. **Load the binding.** Prefer root `AGENTS.md` in a bootstrapped or adopted repo, then read `.agent-project-ops/PRINCIPLES.md`. Confirm: Chat ≠ state; the disposer decides only start confirmations for §11 hits, final acceptance and exceptions; merge ≠ Phase PASS; GitHub `origin` is the only write authority. If this is an existing repo, [adopt-existing-project.md](./adopt-existing-project.md) step 1 (inverted-SoT scan + rewrite) must already be clean — do not open Command Center on an inverted contract.
2. **Fresh-clone hook check.** Run `git config --get core.hooksPath`. A clone does not inherit this local config. In a bootstrapped repo, if it is not `.githooks`, run `bash .agent-project-ops/scripts/install-hooks.sh`. Missing client hook is not permission to push `main`.
3. **Create labels.** Apply `templates/labels.md` (or the pinned snapshot copy) without inventing overlapping status names.
4. **Verify `main` protection.** Require pull requests and disable force/deletion as hosting capability permits. Record observed capability on Command Center: **A** code-owner review enforced, **B** PR-only, or **C** unprotected/unverifiable. Never call B an independent-human-review gate. On GitHub Free private, C is expected: record C and continue (hooks + PR discipline). Do not claim B/A. Do not treat C as a stop-all-work gate. See [ADR 0004](../docs/adr/0004-free-private-capability-c.md).
5. **Open the Command Center issue.** Use `templates/ISSUE_TEMPLATE/command-center.md`. Fill **section 1** (one-glance), project settings (process mode; unrecorded = `standard`), disposer, lead Agent, PIN, default branch, protection capability and Agent roster.
6. **Reconcile remotes.** Only GitHub `origin` is supported; `.agent-project-ops/remotes` records `authority=origin`. Extra remotes or active old role settings stop affected writes. Preserve them for a separately approved project migration, never use them as another write authority.
7. **Open the first work item by process mode.** One core problem only; use backlog status.
   - **`light`:** Open a task using `templates/ISSUE_TEMPLATE/task.md`, with its own contract and no parent Phase. Do not create a Phase issue.
   - **`standard` (including unrecorded mode):** Open Phase-0/Phase-1 using `templates/ISSUE_TEMPLATE/phase.md`.
   Register that task/Phase number in Command Center's existing `## 阶段索引` section. For `light`, change the table's `Phase Issue` column to `Task Issue` in this project's Command Center and put task rows there; an index entry does not create a Phase. Keep the section title `## 阶段索引` for status-generator compatibility. For `standard`, register Phase rows in the same section. Then preview/apply section 1 using `project-automation.py status --cc <cc-number> --phase <task-or-Phase-number>` with the other required status fields; the existing `--phase` flag accepts either Issue type.
8. **Do not implement yet.** Run Freeze on that task (`light`) or Phase (`standard`) before any `feat/` / `fix/` branch. Record the §11 major-change check; on a hit, wait for the disposer's start confirmation or link an existing approval that explicitly covers the scope.

Final acceptance still follows `PRINCIPLES.md` §3: `light` requires the disposer's final acceptance together with release confirmation before each release (or when all confirmed goals are done if nothing releases); `standard` requires it at the end of each Phase. Merge is not acceptance.

## Done when

- [ ] Command Center exists as the single project index, has a filled **section 1**, and names the disposer.
- [ ] Status labels exist.
- [ ] `git config --get core.hooksPath` is `.githooks` for this clone when the tracked hook exists.
- [ ] Command Center records protection capability A/B/C honestly; capability C (expected on GitHub Free private) is recorded and work continues. Never claim B/A when only C was verified.
- [ ] Command Center records origin as the only supported remote and matches `.agent-project-ops/remotes` when present.
- [ ] The first work item matches the mode: a task with its own contract and no Phase (`light`), or a Phase (`standard`). No implementation before Freeze and any required start confirmation.
- [ ] That task/Phase number is registered in Command Center's compatible index; section 1 can be generated by status preview before apply.
- [ ] Agent can find the pinned/current playbooks without the original bootstrap chat.

## Anti-patterns

- Treating the methodology repository as the product repository.
- Treating a tracked hook file as proof `core.hooksPath` is active after clone.
- Calling PR-only protection “human approval enforced” when Agent and disposer share an identity.
- Treating Free-private capability C as “stop all work” or claiming B/A when only C was verified.
- Skipping Command Center and tracking work only in chat.
- Pushing “just this once” to `main`.
- Adding a second write authority or using another host as a fallback.
- Embedding business SOP into this methodology repository.
- Starting this playbook while `AGENTS.md` still names a non-GitHub host as production/write SoT.
