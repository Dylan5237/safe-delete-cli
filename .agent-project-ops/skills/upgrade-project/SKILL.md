---
name: upgrade-project
description: >
  Upgrade a previously APO-bound project's rules to a chosen released version.
  Preview exact owned-file changes, preserve project policy and business files,
  export a reviewed Git patch, and use an isolated task worktree. Do not merely
  change PIN, overwrite custom rules, or imply local files update GitHub state.
  Also triggered by the URL-first Chinese request:
  使用 https://github.com/Dylan5237/agent-project-ops 更新当前项目的apo规则。
---

# Upgrade an existing APO project

## URL-first short prompt (preferred user entry)

Treat `使用 https://github.com/Dylan5237/agent-project-ops 更新当前项目的apo规则。` as the complete user **intent**. Do not ask the user to type a Skill name, pre-install a package or repeat a long prompt. In a capable host, inspect the GitHub repository URL and select its latest **published stable Release** and verified exact tag/commit SHA (unless the user specified a version). Fetch or use a trusted **full-history Git clone**, never an unverified moving `main` or ZIP without Git history, then read the matching `skills/upgrade-project/SKILL.md`. If network/local Git/permissions are missing, explain the blocker and manual fallback; do not claim a successful upgrade.

The prompt authorizes **discovery and read-only preview**, not applying a patch, silently changing PIN, modifying other repositories or merging a PR. First inspect the current project's real binding, classify project state, use its approved task base, and obtain a separate human confirmation for the resulting exact `plan_id`. Bootstrap/Adoption is different from upgrading a previously bound project.

Use when the user asks to update a project's old APO mechanism/rules. This is
an upgrade of the **selected project only**, not authorization to migrate other projects,
change business behavior, deploy, or accept unrelated Phases.

## Preconditions and source

1. Read the target's `AGENTS.md`, `.agent-project-ops/PIN`, remotes and current
   Command Center. Identify its approved baseline, project-specific policies,
   current work and any required scope decision. Keep explicit project review
   requirements even when generic APO no longer mandates a particular vendor.
2. Use a **separate trusted, clean Git clone** of the pinned methodology URL,
   checked out at the chosen release tag. Keep full history: the old PIN SHA
   must exist locally. Never run bootstrap over the existing target.
3. Use Git + Python 3.10 or newer (Windows: Python and Git Bash for shell steps).
   The release clone contains `scripts/prepare-upgrade.py`. Do not infer that
   a copied `.agent-project-ops` snapshot is itself a full methodology clone.
   Active legacy remote roles or extra remotes are unsupported by the new rules: stop for an explicit project migration review, without changing remote configuration. Known old adapter and script paths remain legacy descriptors so unmodified retired files can be removed and restored by the reviewed patch. A custom retired adapter must conflict rather than be deleted.
4. Stop on dirty work, an unresolvable old PIN, changed upstream identity,
   symlinks, custom snapshot changes or uncertain ownership. Do not auto-stash,
   reset, run destructive cleanup, rewrite the old PIN or bypass a conflict.

## Preview, isolate, and obtain an actual decision

5. Create or select a **dedicated upgrade worktree and topic branch** using the
   project's approved baseline. The original checkout and commit remain the
   backup; record the baseline SHA. Do not work on the default branch.
6. For selected-layout releases, read all three initialization choices from the reviewed project-config. If a legacy project has none, collect explicit process_mode, agent_tools and external_tools choices and pass all three flags to both preview and patch export. Partial settings, invalid choices or conflict with existing choices stop. Existing config entries are preserved; new reviewed choices are appended in the patch and bound to plan_id. Never infer choices from installed folders.

   If CLAUDE.md contains custom text, review and migrate it into AGENTS.md first using project-settings.py migrate-claude (preview, then explicit --apply under project authorization). Commit that separately reviewed target baseline before the clean-target preview. The upgrade planner refuses unmigrated custom CLAUDE text instead of preserving a multiline import or dropping rules. An unmodified historical bridge is normalized by the upgrade patch.

   From the trusted release clone, run:

   ```bash
   python3 scripts/prepare-upgrade.py --project /absolute/upgrade-worktree
   ```

   It reads Git objects from the old PIN and new release, reconstructs known
   bootstrap-owned files, merges nonconflicting project bridge changes, and
   emits a JSON plan. It does **not** write the target, contact GitHub, commit,
   push, or change Git configuration. It preserves remotes, existing project-config entries,
   business files and project-specific appended/prefixed rules.
7. Show the old/new SHA, exact changed paths, policy changes, preserved data,
   conflicts and `plan_id`. Obtain confirmation to apply this specific plan.
   Reuse a supported host-native choice tool when needed; otherwise use normal
   dialogue. Headless execution needs explicit approval, not a guessed answer.

## Export a patch; let Git perform the reviewed local change

8. Save the plan and patch **outside** the target/source worktrees. With the
   exact approved `plan_id`:

   ```bash
   python3 scripts/prepare-upgrade.py --project /absolute/upgrade-worktree \
     --patch --expect-plan PLAN_ID > /safe/upgrade.patch
   ```

   Capture the command's exit code. A nonzero exit is a stop, never pipe errors
   into Git. The receipt on stderr includes the patch checksum and baseline.
9. Verify the worktree is still clean at the recorded baseline, inspect the
   patch, and run `git apply --check /safe/upgrade.patch` in that worktree.
   Only after successful checking and authorization run `git apply` with that
   same patch. Never use `--reject`, `--unsafe-paths`, or force-like fallbacks.
10. Inspect `git diff`, verify the new PIN and preserved project settings,
    rerun appropriate project checks, then use the normal upgrade PR. Do not
    auto-merge, deploy or self-Accept. A repeated preview after committing the
    identical new PIN reports `UP_TO_DATE`.

## Reconcile project rules, not just the local snapshot

11. The tool explicitly returns `PENDING_RECONCILIATION` for the GitHub control
    plane. Review the **selected project's** existing CC/Phase/ADR and root
    project-specific text for obsolete inherited instructions. Propose
    replacing only obsolete **generic inherited requirements**, preserve actual
    project-approved checks, owners, active work and history. Obtain the needed
    project decision and update CC to reference the upgrade PR/new PIN.
12. Missing GitHub access means **LOCAL PATCH READY, CONTROL PLANE PENDING**,
    not "project upgraded". Only report completion when the target project's
    reviewed rule update and control-plane record agree. Never fabricate old
    Freeze/Accept or erase the historical version's evidence.

## After the upgrade PR merges: switch on automatic retirement

13. Only after the upgrade PR is merged (the project now ships
    `.agent-project-ops/scripts/tidy-worktrees.sh`):
    - Enable GitHub **Automatically delete head branches**
      (`gh repo edit OWNER/REPO --delete-branch-on-merge`; needs admin, else
      give the user that command). If a long-lived branch such as `develop`
      reaches the default branch through PRs and cannot be protected from
      deletion, ask first instead of enabling it.
    - From the primary checkout run `tidy-worktrees.sh` (read-only plan). Turn
      the inherited backlog into **one** decision request: what would be
      retired (merged), what would be archived then deleted (closed), and every
      `keep` line with its reason; old unmerged branches may be proposed for
      `--abandon` individually or as a listed batch.
    - After approval: `tidy-worktrees.sh --apply`, then `--abandon <branch>` for
      each approved branch, and record the final `apo-tidy:` line on the upgrade
      Issue / CC. Never delete by hand; leftovers that need investigation
      (diverged, no PR, other tools' folders) go to `repo-reconciliation-cleanup`.

## Rollback

Before commit, keep the exact exported patch and baseline. First run
`git apply --reverse --check /safe/upgrade.patch`; only if it succeeds and rollback
is requested, run `git apply --reverse` with that patch. Later edits that conflict
must stop rollback, not be overwritten. After commit/merge, use an ordinary
reviewed Git revert instead. The original worktree/base commit was never changed
by the patch generator. Do not remove a worktree containing unrelated work.

Custom hand-maintained bindings that cannot be reconstructed safely are **not**
automatically supported. Provide a manual three-way review plan; do not offer
an overwrite-all escape hatch. See `docs/UPGRADE.md` in the release clone.
