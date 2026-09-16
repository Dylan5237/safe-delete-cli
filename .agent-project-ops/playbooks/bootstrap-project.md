# Playbook: Bootstrap project / 初始化并绑定项目

## Goal

Create a generic project repository that is born with durable `agent-project-ops` binding instead of relying on the bootstrap chat to be remembered later.

Bootstrap creates/binds the repository. It does **not** Freeze a product Phase, implement product code, or declare Phase PASS.

## Preconditions

- Run from a real git checkout of `agent-project-ops`; supported bootstrap requires a real methodology commit SHA.
- `git` is available. GitHub creation additionally requires an authenticated `gh` CLI.
- A real disposer GitHub handle is known; placeholder `@DISPOSER` is not accepted.
- Optional projection URL contains no embedded credential/query token.

## Supported path

```bash
scripts/bootstrap-project.sh \
  --name example-project \
  --disposer @example \
  --no-projection
```

Use `--dry-run` first when evaluating a new environment. Use `--skip-github` only for local scaffold/testing.

Optional projection:

```bash
scripts/bootstrap-project.sh \
  --name example-project \
  --disposer @example \
  --projection-url git@gitlab.example:group/example-project.git
```

The remote is named `projection`; it is never a feature-push target.

## What bootstrap writes

- root `AGENTS.md` plus adapters for supported Agent tools (`CLAUDE.md`, Cursor rule, Copilot instructions, optional Aider/Continue files)
- `.agents/skills/*` and `.claude/skills/*` thin wrappers
- `.agent-project-ops/` pinned methodology snapshot with real `PIN` SHA
- `.agent-project-ops/remotes` (clone-portable classification; Git config itself is not portable)
- `.githooks/pre-push` plus local `core.hooksPath=.githooks`
- `.worktrees/` locally and a gitignore rule for it
- GitHub Issue/PR templates and CODEOWNERS binding paths

If a later user/Agent **clones** the business repo, the hook file arrives but `core.hooksPath` does not. Before first push it must run:

```bash
bash .agent-project-ops/scripts/install-hooks.sh
```

The root `AGENTS.md` carries this check.

## GitHub protection capability

Server policy is reported as observed capability, not marketing language:

- **A — code-owner review enforced:** PR required and code-owner/approval gate verified.
- **B — PR-only:** direct default-branch updates are blocked, but a writer may still be able to self-merge. This is the safe default when the Agent uses the same GitHub identity as the human owner.
- **C — unprotected/BLOCKED:** requested branch protection could not be enabled or verified.

Default bootstrap requests **B**. `--require-codeowner-review` requests **A**, but use it only when repository identity/ownership actually supports an independent reviewer; otherwise a single-user repository can be locked into an unusable review gate.

If protection cannot be enabled, bootstrap returns a blocked result after repository creation. Do not start feature work; record the capability gap on Command Center.

## After bootstrap

1. Run [start-project.md](./start-project.md).
2. Create labels and Command Center.
3. Record the PIN, registered remotes, and protection capability.
4. Open one Phase issue.
5. Freeze before creating implementation work.

## Done when

- [ ] Generated project is a git repository with a real methodology SHA in `.agent-project-ops/PIN`.
- [ ] Binding files and project skill wrappers exist.
- [ ] `.agent-project-ops/remotes` names `origin` as authority and only requested projection remotes.
- [ ] `core.hooksPath=.githooks` in the bootstrap checkout.
- [ ] Fresh-clone instructions explicitly reinstall the hook configuration before first push.
- [ ] `.worktrees/` exists locally and is ignored.
- [ ] No generated file contains credential-bearing remote URLs.
- [ ] If GitHub was created, `origin` is the GitHub authority and protection is reported as A, B, or C.
- [ ] No product Phase has been self-Accepted by bootstrap.

## Anti-patterns

- Downloading the methodology as ZIP and accepting `sha=unknown`.
- Treating the presence of `.githooks/pre-push` as proof the hook is installed after clone.
- Calling PR-only protection “human approval enforced.”
- Requiring one approval on a single-identity repository without understanding the lockout/self-review semantics.
- Adding a second write remote for convenience.
- Using a projection failure as permission to retarget feature pushes.
