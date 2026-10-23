# Playbook: Adopt an existing project / 存量项目接入

Adoption binds an existing nonempty repository without replacing its business files. It is not greenfield bootstrap and not an upgrade of an existing PIN.

## Mandatory rule audit before PIN

1. Read the project's AGENTS.md and all inherited tool rule files. The scanner still reads old adapter files to detect conflicting instructions; that is legacy safety inspection, not current tool support.
2. Run `python3 scripts/scan-inverted-sot.py --root <repo>` from a trusted methodology checkout. An inverted rule naming a non-GitHub host as write authority or demoting GitHub to mirror-only is MUST-FIX. A PIN binding is incomplete while such a rule remains.
3. Rewrite the confirmed project rule contract to match [templates/AGENTS.md](../templates/AGENTS.md): GitHub origin is the only supported remote, topic branches use origin and the default branch receives PRs. Preserve project-specific policies and historical evidence; changing them needs the project's own authority.
4. Extra remotes or active old role settings are unsupported. Stop affected writes and obtain an explicit project migration decision; do not repoint URLs, remove remotes or publish to another host automatically.
5. Distinguish the write-authority tip from an actual release/deploy manifest SHA. A deployed SHA is a runtime fact, never a second write authority. Unknown deployed identity stays UNKNOWN.

## Binding and verification

- Obtain the project's scope/owner decision, preserve a clean baseline and work on its task branch or isolated worktree.
- Use an exact, clean, complete-history methodology source. Record canonical URL, full SHA, ref and fetch date in PIN; never bind an unverified moving source.
- Collect all three project choices as in bootstrap, using the declaration in templates/project-options.json; no unattended defaults for missing choices. Existing settings and conflicting owned directories require review, never overwrite.
- Preserve CLAUDE.md project text in AGENTS.md BEFORE replacing it with the single @AGENTS.md import line. On the approved task branch, preview with python3 scripts/project-settings.py migrate-claude --root /project from the trusted methodology source. Review the preserved text and any rule contradictions; only then use the same command with --apply. The command writes preserved AGENTS content first, supports repeat execution, and refuses symlink/binary rule files. Commit and review the diff before running a clean-target upgrade preview.
- Install the approved snapshot, AGENTS binding, one-line CLAUDE bridge, canonical .agents/skills, selected host copies and hooks without replacing business files or custom rules. The single remote registry records authority=origin. Copy external integration instructions only when selected; do not connect services.
- Run the installed project-settings.py check and check-core. Selected copies must match every canonical file; WorkBuddy uses .codebuddy/skills in Craft mode. Missing or extra files stop the binding rather than triggering a cleanup.
- Check the configured hook in this clone; cloning does not inherit core.hooksPath.
- Re-run the rule scan, inspect all diffs and run project checks. Follow [start-project.md](start-project.md) for the live GitHub Command Center and actual protection capability.
- Local files do not update GitHub Issues. Reconcile current tasks, owners, decisions and actual evidence; missing access leaves control-plane work pending.

## Completion

The scanner is clean, PIN and source match, original business/project rules are preserved, only origin is supported, GitHub state agrees with the reviewed binding, and no Agent has fabricated Freeze ACK or final acceptance. If any ownership/source/authority fact is unknown, stop and record the gap.
