---
name: bootstrap-project
description: >
  Initialize a new generic git project using Dylan5237/agent-project-ops:
  create a local folder, durable Agent binding files, a pinned methodology
  snapshot, .worktrees/ and GitHub origin as the only supported remote; use for one-shot initialization, not business-domain setup.
  Also triggered by the URL-first Chinese request:
  使用 https://github.com/Dylan5237/agent-project-ops 初始化当前项目。
---

# Bootstrap project

## URL-first short prompt (preferred user entry)

Treat `使用 https://github.com/Dylan5237/agent-project-ops 初始化当前项目。` as a complete **intent**, not a request for the user to install this Skill, memorize a CLI command, or paste a longer prompt. An Agent with GitHub, filesystem and Git capabilities should inspect the supplied repository URL, resolve the **latest published stable Release** (or an explicitly named version), verify the exact tag/commit SHA, and read its corresponding `PRINCIPLES.md`, `skills/bootstrap-project/SKILL.md` and applicable playbooks from a trusted Git checkout. Do not silently use moving `main` as a release identity.

Inspect the **current project** before writing. A new/empty project follows this Bootstrap Skill; a nonempty repository not yet bound to APO follows `playbooks/adopt-existing-project.md`; a previously bound project is inspected/reconciled instead of reinitialized. Never overwrite an existing working tree or create/push a GitHub repository without authorization. If GitHub/network, local Git/filesystem or required permissions are unavailable, clearly report the limitation and a manual fallback rather than inventing completion.

Read [PRINCIPLES.md](../../PRINCIPLES.md) first. This skill creates and binds a repository; it does not Freeze product scope, implement features, or Accept phases.

Current initialization procedure: [bootstrap playbook](../../playbooks/bootstrap-project.md). Binding and safety contract: [PRINCIPLES](../../PRINCIPLES.md). Free-private C posture: [protection steps](../../playbooks/bootstrap-project.md#steps). These references are included in the pinned project snapshot.

## Required path

1. Confirm the destination is new/empty. Existing repositories are adoption, not greenfield bootstrap: follow [adopt-existing-project](../../playbooks/adopt-existing-project.md). Audit inherited rule files and fix an inverted authority contract before PIN binding.
2. Collect a real project slug and real disposer GitHub handle. Do not emit placeholder @DISPOSER. Also collect process_mode (light/standard), nonempty agent_tools multi-selection, and external_tools (default none), using IDs/labels from templates/project-options.json. Use native host choices if available, otherwise ordinary conversation. Supply all three CLI flags explicitly; --yes or non-TTY input must fail before target writes when any is missing. Never silently choose tools for the disposer.
3. Support GitHub `origin` only. Additional remote roles are not generated or supported. Stop if an existing project needs a separate migration decision.
4. Run `scripts/bootstrap-project.sh --dry-run ...` first when environment behavior is uncertain, then the real command.
5. After scaffold, verify PIN contains a real SHA, remotes records authority=origin, and project-config / Command Center record all three choices. .agents/skills is the canonical source; selected hosts get identical full-tree copies. WorkBuddy uses .codebuddy/skills and AGENTS.md in Craft mode; Ask was not verified. CLAUDE.md must contain only @AGENTS.md. Run the installed project-settings.py check and check-core; the generated pre-push repeats these checks. Optional integration instructions are copied only when selected and never connect accounts or services.
6. Verify `git config --get core.hooksPath` is `.githooks` in the bootstrap checkout. Remember a later clone will not inherit it; root `AGENTS.md` instructs the next Agent to run the installer.
   After editing canonical project skills, use `project-settings.py sync-skills`
   to preview selected-host copies; inspect differences, then explicitly apply
   with the matching plan_id. See [automation](../../playbooks/automation.md).
7. If GitHub creation is enabled, read the reported protection capability: A (code-owner review enforced), B (PR-only), or C (unprotected/unverifiable). Never upgrade the wording beyond what was verified. On GitHub Free **private** repos, C is **expected**: record C on Command Center and continue. Do not treat C as init failure or “do not start feature work.” Do not require Pro to finish init.
8. Run `playbooks/start-project.md` next (labels, Command Center, first work item). For `light`, open a task with its own contract and no Phase; for `standard` (including unrecorded mode), open a Phase. Register that work item in the Command Center index as the playbook describes so section 1 can be generated. Freeze that task/Phase and wait for any required §11 start confirmation before `feat/` / `fix/` implementation. Final acceptance and release confirmation still follow `PRINCIPLES.md` §3.

## Important identity limit

If the local Agent and the human disposer use the **same GitHub identity**, GitHub cannot distinguish which one clicked/pushed/merged. CODEOWNERS cannot create a human-vs-Agent security boundary in that configuration. Default bootstrap therefore requests PR-only protection (B); request code-owner review (A) only when the repository has a genuinely independent reviewer/identity and the user wants that gate.

## Protection honesty

- Report A/B/C as verified. Never claim B/A when only C was verified.
- GitHub Free **private** → C is expected. Record C on Command Center and continue. Do not require Pro to finish init. Do not treat C as bootstrap failure.
- Client hooks + PR discipline still apply under C. Do not claim server protection exists.

## Fail closed

- Methodology source is not a git checkout / SHA cannot be determined → stop; supported bootstrap never writes silent `sha=unknown`.
- GitHub creation requested but `gh` is unavailable/unauthenticated → stop.
- Unknown remote → no push.
- Destination exists and is not empty → stop; that is [adoption](../../playbooks/adopt-existing-project.md). Inverted `AGENTS.md` SoT → fail closed (PIN not complete).
- Do not use `--no-verify` as a workflow shortcut.
