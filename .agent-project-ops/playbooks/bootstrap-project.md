# Playbook: Bootstrap project / 新项目初始化

For a new/empty repository only. Existing repositories use [adopt-existing-project.md](adopt-existing-project.md); never overwrite an existing working tree.

## Preconditions

- A trusted clean full-history methodology Git checkout at the verified selected release SHA. A ZIP is not a provenance source.
- Git, Bash and Python; authenticated gh and explicit authorization when creating a GitHub repository.
- A real project slug and named disposer, no placeholder identity.

## Steps

1. Inspect the destination. If it is nonempty, scan inherited rules and use adoption; an inverted authority contract must be fixed before PIN binding.
2. Collect process mode, Agent tools (nonempty multi-select), and optional external tools using the host's native choices or ordinary conversation. Read IDs/labels from templates/project-options.json. External tools default to none; never infer an Agent selection. Headless input and --yes require all three explicit flags. Then use the selected release's --help / --dry-run and the approved command, for example:

   ```bash
   bash scripts/bootstrap-project.sh --name example --dir ../example --disposer @OWNER --process-mode standard --agent-tools codex,claude --external-tools none --skip-github --yes
   ```

3. Only GitHub origin is supported. Record choices in project-config and Command Center. AGENTS.md owns all rules; CLAUDE.md is exactly one @AGENTS.md line. .agents/skills is always the canonical source; only selected host copies and external integration guides are installed. WorkBuddy's .codebuddy/skills and AGENTS entry are verified in Craft mode; Ask is not a verified entry. No service connection or publishing channel is installed.
4. Verify PIN SHA equals the clean source HEAD, authority=origin, core.hooksPath=.githooks and discoverable Skill wrappers. Run python3 .agent-project-ops/scripts/project-settings.py check --root . and check-core --root .; generation and the generated pre-push hook use these checks too. File-set/content drift and extra unselected adapters fail closed; do not delete project-owned files to make them pass.
5. With approved GitHub creation, verify the observed protection capability: A independent code-owner gate, B PR-only, C unavailable/unverifiable. C on GitHub Free private may be expected; record it and continue honestly. Hooks remain bypassable. Shared human/Agent identity is not an independent review boundary.
6. Continue with [start-project.md](start-project.md): labels, Command Center, process mode (unrecorded = standard), first task/Phase contract. No implementation before freeze and any required start confirmation.

## Stop conditions

Unknown source SHA, dirty copied source, unsafe URL, nonempty destination, placeholder disposer, missing required GitHub permission or unsupported remote option stops before a partial binding can be claimed complete. Bootstrap never rewrites an existing project or invents `sha=unknown`.
