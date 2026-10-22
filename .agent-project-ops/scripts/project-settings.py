#!/usr/bin/env python3
"""Select, generate and verify project bindings; preserve old rule text explicitly."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import stat
import subprocess
import sys
import tempfile
import uuid

KEYS = ("process_mode", "agent_tools", "external_tools")
OTHER_KEYS = {"task_base", "max_worktrees", "worktree_mode"}
BRIDGE = "@AGENTS.md\n"


class Invalid(ValueError):
    pass


def catalog(source: Path) -> dict:
    data = json.loads(regular(source / "templates/project-options.json").decode("utf-8"))
    if data.get("layout_version") != 1:
        raise Invalid("unsupported project options layout")
    for group in ("agent_tools", "external_tools"):
        if not isinstance(data.get(group), dict) or not data[group]:
            raise Invalid("invalid option group: " + group)
        for key, item in data[group].items():
            if not re.fullmatch(r"[a-z][a-z0-9-]*", key):
                raise Invalid("invalid option id")
            if group == "external_tools" and item["guide"] != key + ".md":
                raise Invalid("invalid guide path")
            if group == "agent_tools" and item["skills_dir"] not in (".agents/skills", ".claude/skills", ".codebuddy/skills"):
                raise Invalid("unsupported skills directory")
    return data


def subset(value: str, options: dict, *, none: bool = False) -> str:
    if none and value == "none":
        return value
    tokens = value.split(",")
    if not value or len(set(tokens)) != len(tokens) or any(t not in options for t in tokens):
        raise Invalid("expected a nonempty, unique comma-separated subset: " + ",".join(options))
    return ",".join(key for key in options if key in tokens)


def normalize(data: dict, mode: str, agents: str, external: str) -> dict[str, str]:
    if mode not in ("light", "standard"):
        raise Invalid("process_mode must be light or standard")
    return dict(process_mode=mode,
                agent_tools=subset(agents, data["agent_tools"]),
                external_tools=subset(external, data["external_tools"], none=True))


def config_values(text: str, *, strict: bool = True) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key in result or (strict and key not in set(KEYS) | OTHER_KEYS):
            raise Invalid("invalid, duplicate or unknown project-config entry: " + line)
        result[key] = value
    return result


def settings_text(settings: dict[str, str]) -> str:
    return "".join(key + "=" + settings[key] + "\n" for key in KEYS)


def methodology(root: Path) -> Path:
    snapshot = root / ".agent-project-ops"
    no_links(snapshot)
    if (snapshot / "templates/project-options.json").exists() or (snapshot / "PIN").exists():
        return snapshot
    if (root / "templates/project-options.json").is_file() and (root / "scripts/project-settings.py").is_file():
        return root
    return snapshot


def no_links(path: Path) -> None:
    """Reject links at every existing component, including Windows junctions."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Invalid("links/reparse points are unsupported: " + str(item))


def sync_root(path: Path) -> Path:
    absolute = path.absolute()
    # macOS exposes ordinary temporary/project paths through OS-owned aliases.
    # Normalize only these known system prefixes; user links below them still
    # pass through no_links before resolve can hide a junction/symlink.
    if sys.platform == "darwin":
        for name in ("var", "tmp", "etc"):
            prefix = Path("/") / name
            if absolute.is_relative_to(prefix) and prefix.resolve() == Path("/private") / name:
                absolute = prefix.resolve() / absolute.relative_to(prefix)
                break
    no_links(absolute)
    return absolute.resolve()


def storage_volume(path: Path) -> tuple[int, str]:
    """Identify storage before creating anything, including absent target parents."""
    no_links(path)
    probe = path
    while not probe.exists():
        probe = probe.parent
    return probe.stat().st_dev, probe.anchor.casefold() if os.name == "nt" else ""


def regular(path: Path) -> bytes:
    no_links(path)
    if not path.is_file():
        raise Invalid("expected a regular file: " + str(path))
    return path.read_bytes()


def files_below(path: Path):
    no_links(path)
    if not path.is_dir():
        raise Invalid("expected a real directory: " + str(path))
    pending = [path]
    while pending:
        for entry in pending.pop().iterdir():
            no_links(entry)
            if entry.is_file():
                yield entry
            elif entry.is_dir():
                pending.append(entry)
            else:
                raise Invalid("special directory entry: " + str(entry))


def tree(path: Path) -> dict[str, bytes]:
    result = {entry.relative_to(path).as_posix(): regular(entry) for entry in files_below(path)}
    if not result or not any(p.endswith("/SKILL.md") for p in result):
        raise Invalid("no skill manifests: " + str(path))
    return result


def layout(path: Path) -> dict:
    """Include empty directories and POSIX permissions, without following links."""
    no_links(path)
    if not path.is_dir():
        raise Invalid("expected a real directory: " + str(path))
    result = {}
    pending = [path]
    while pending:
        entry = pending.pop()
        no_links(entry)
        if not entry.is_dir() and not entry.is_file():
            raise Invalid("special directory entry: " + str(entry))
        result[entry.relative_to(path).as_posix()] = {
            "kind": "dir" if entry.is_dir() else "file",
            "mode": stat.S_IMODE(entry.stat().st_mode) & 0o777 if os.name == "posix" else None}
        if entry.is_dir():
            pending.extend(entry.iterdir())
    return result


def materialize(dest: Path, contents: dict, structure: dict) -> None:
    for name, item in structure.items():
        if item["kind"] == "dir":
            (dest / name).mkdir(parents=True, exist_ok=True)
    for name, raw in contents.items():
        file = dest / name
        file.write_bytes(raw)
        if structure[name]["mode"] is not None:
            file.chmod(structure[name]["mode"])
    # Apply directory permissions last so read-only source folders can be built.
    for name in sorted(structure, key=lambda p: len(PurePath(p).parts), reverse=True):
        item = structure[name]
        if item["kind"] == "dir" and item["mode"] is not None:
            (dest / name).chmod(item["mode"])


def verify_bridge(path: Path) -> None:
    if regular(path).decode("utf-8").replace("\r\n", "\n") not in (BRIDGE, BRIDGE.rstrip("\n")):
        raise Invalid("CLAUDE.md must contain only @AGENTS.md: " + str(path))


def checked_settings(root: Path, data: dict) -> dict[str, str]:
    values = config_values(regular(root / ".agent-project-ops/project-config").decode("utf-8"))
    try:
        return normalize(data, *(values[key] for key in KEYS))
    except KeyError as exc:
        raise Invalid("missing project setting: " + str(exc)) from exc


def generate(root: Path, source: Path, settings: dict[str, str]) -> None:
    data = catalog(source)
    verify_bridge(root / "CLAUDE.md")
    no_links(root / ".agent-project-ops")
    source_tree = tree(root / ".agents/skills")
    selected = settings["agent_tools"].split(",")
    destinations = []
    for key, item in data["agent_tools"].items():
        target = root / item["skills_dir"]
        if item["skills_dir"] == ".agents/skills":
            continue
        no_links(target)
        if target.exists():
            raise Invalid("refusing to replace existing skill directory: " + str(target))
        if key in selected:
            destinations.append(target)
    guides = []
    selected_external = settings["external_tools"].split(",")
    for key, item in data["external_tools"].items():
        if key in selected_external:
            raw = regular(source / "integrations" / item["guide"])
            dest = root / ".agent-project-ops/integrations" / item["guide"]
            no_links(dest)
            if dest.exists():
                raise Invalid("refusing to replace guide: " + str(dest))
            guides.append((dest, raw))
    config = root / ".agent-project-ops/project-config"
    no_links(config)
    if config.exists():
        raise Invalid("refusing to replace project-config")
    structure = layout(root / ".agents/skills")
    for dest in destinations:
        dest.mkdir(parents=True)
        materialize(dest, source_tree, structure)
    for dest, raw in guides:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    config.write_text(settings_text(settings), encoding="utf-8", newline="\n")


def check(root: Path) -> None:
    source = methodology(root)
    no_links(source)
    data = catalog(source)
    settings = checked_settings(root, data)
    verify_bridge(root / "CLAUDE.md")
    original = tree(root / ".agents/skills")
    for key, item in data["agent_tools"].items():
        if item["skills_dir"] == ".agents/skills":
            continue
        dest = root / item["skills_dir"]
        no_links(dest)
        if key in settings["agent_tools"].split(","):
            if tree(dest) != original or layout(dest) != layout(root / ".agents/skills"):
                raise Invalid("skill copy drift: " + str(dest))
        elif dest.exists():
            raise Invalid("unselected skill adapter exists: " + str(dest))
    selected = settings["external_tools"].split(",")
    expected = {item["guide"] for key, item in data["external_tools"].items() if key in selected}
    guide_dir = root / ".agent-project-ops/integrations"
    no_links(guide_dir)
    actual = {p.name for p in guide_dir.iterdir()} if guide_dir.exists() else set()
    if actual != expected:
        raise Invalid("selected integration guide set differs")
    for name in expected:
        if not regular(guide_dir / name).strip():
            raise Invalid("empty integration guide")
    cc = regular(root / ".github/ISSUE_TEMPLATE/command-center.md").decode("utf-8")
    for key in KEYS:
        values = re.findall(r"(?<![\w])" + key + r"=([^\s（`]*)", cc)
        if values != [settings[key]]:
            raise Invalid("Command Center setting differs: " + key)


def check_core(root: Path) -> None:
    source = methodology(root)
    data = catalog(source)
    files = {source / "PRINCIPLES.md", source / "templates/AGENTS.md", source / "templates/CLAUDE.md"}
    for directory in ("playbooks", "skills", "scripts"):
        folder = source / directory
        no_links(folder)
        if folder.exists():
            files.update(p for p in files_below(folder)
                         if (directory == "playbooks" and p.suffix == ".md")
                         or (directory == "skills" and p.name == "SKILL.md")
                         or (directory == "scripts" and p.suffix in (".sh", ".py")))
    # Only APO-owned source files participate in the name boundary. Project
    # instructions may name selected tools; the root bridge is checked below.
    names = [name.casefold() for key, item in data["external_tools"].items()
             for name in [key, item["label"], *item["names"]]]
    for file in sorted(files):
        text = regular(file).decode("utf-8").casefold()
        if any(name in text for name in names):
            raise Invalid("external tool name in core: " + str(file))
    verify_bridge(source / "templates/CLAUDE.md")
    if (root / "CLAUDE.md").exists():
        verify_bridge(root / "CLAUDE.md")


def replace_text(path: Path, text: str) -> None:
    info = path.stat()
    fd, name = tempfile.mkstemp(prefix=".apo-rule-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        if os.name == "posix":
            os.chown(name, info.st_uid, info.st_gid)
        os.chmod(name, stat.S_IMODE(info.st_mode))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.remove(name)


def migrate(root: Path, apply: bool) -> None:
    agents, claude = root / "AGENTS.md", root / "CLAUDE.md"
    old_agents, old_claude = regular(agents), regular(claude)
    a = old_agents.decode("utf-8")
    c = old_claude.decode("utf-8").replace("\r\n", "\n")
    if "\0" in a + c or not a.strip():
        raise Invalid("rule files must be nonempty UTF-8 text without NUL")
    if c in (BRIDGE, BRIDGE.rstrip("\n")):
        print("UNCHANGED: one-line CLAUDE.md")
        return
    lines = c.splitlines()
    if lines and lines[0] == "@AGENTS.md":
        lines = lines[1:]  # Only the leading bridge is owned; preserve examples below it.
    custom = "\n".join(lines).strip("\n")
    marker = "<!-- apo-claude-preserved: " + hashlib.sha256(custom.encode()).hexdigest() + " -->"
    addition = "\n\n## Preserved project instructions\n\n" + marker + "\n\n" + custom + "\n"
    if marker in a and custom not in a:
        raise Invalid("existing migration marker conflicts with preserved text")
    merged = a if not custom or marker in a else a.rstrip("\n") + addition
    print("APPLY" if apply else "PREVIEW", ": preserve CLAUDE.md text in AGENTS.md, then write one-line import")
    if apply:
        if regular(agents) != old_agents or regular(claude) != old_claude:
            raise Invalid("rule files changed during migration")
        # Write preserved content first. A failure cannot discard the old rules.
        replace_text(agents, merged)
        replace_text(claude, BRIDGE)


def sync_skills(root: Path, apply: bool, expect_plan: str) -> None:
    """Preview a complete selected-host copy; quarantine old trees before swap."""
    source = methodology(root)
    data = catalog(source)
    config = regular(root / ".agent-project-ops/project-config")
    settings = checked_settings(root, data)
    original = tree(root / ".agents/skills")
    source_layout = layout(root / ".agents/skills")
    destinations = []
    changes = []
    snapshot = {"root": str(root), "config": hashlib.sha256(config).hexdigest(),
                "source": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(original.items())},
                "source_layout": source_layout,
                "targets": {}}
    for key, item in data["agent_tools"].items():
        directory = item["skills_dir"]
        if directory == ".agents/skills":
            continue
        dest = root / directory
        no_links(dest)
        if key not in settings["agent_tools"].split(","):
            if dest.exists():
                raise Invalid("unselected skill adapter exists; reconcile settings first: " + directory)
            continue
        old = {p.relative_to(dest).as_posix(): regular(p) for p in files_below(dest)} if dest.exists() else None
        old_layout = layout(dest) if old is not None else {}
        snapshot["targets"][directory] = None if old is None else {
            "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(old.items())}, "layout": old_layout}
        old_files = old or {}
        delta = []
        for name in sorted(original.keys() | old_files.keys()):
            if name not in original:
                action = "QUARANTINE_EXTRA"
            elif name not in old_files:
                action = "ADD"
            elif original[name] != old_files[name]:
                action = "UPDATE"
            elif source_layout[name] != old_layout.get(name):
                action = "UPDATE_MODE"
            else:
                continue
            delta.append(f"{action} {directory}/{name}")
            before, after = old_files.get(name, b""), original.get(name, b"")
            try:
                delta.extend(difflib.unified_diff(before.decode("utf-8").splitlines(),
                             after.decode("utf-8").splitlines(),
                             fromfile=directory + "/" + name, tofile=".agents/skills/" + name, lineterm=""))
            except UnicodeDecodeError:
                delta.append("binary sha256: " + hashlib.sha256(before).hexdigest() + " -> " + hashlib.sha256(after).hexdigest())
        for name in sorted(source_layout.keys() | old_layout.keys()):
            new_item, old_item = source_layout.get(name), old_layout.get(name)
            if new_item == old_item or not any(item and item["kind"] == "dir" for item in (new_item, old_item)):
                continue
            delta.append(f"DIRECTORY {directory}/{name}: {old_item} -> {new_item}")
        if delta or old is None:
            changes.extend(delta)
            destinations.append((dest, old, old_layout))
    plan_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    print("\n".join(changes) if changes else "UNCHANGED: selected skill copies match")
    print("plan_id=" + plan_id)
    if not apply:
        print("PREVIEW: no files written; confirm with --apply --expect-plan " + plan_id)
        return
    if not expect_plan or expect_plan != plan_id:
        raise Invalid("STALE_PLAN: preview first; source, targets or settings changed")
    if not destinations:
        return
    # The common directory survives linked-worktree retirement. Validate every
    # recovery/target path and volume before staging or moving any user content.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    no_links(root / ".git")
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", env=env, check=True)
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, encoding="utf-8", env=env, check=True)
    if Path(top.stdout.strip()).resolve() != root:
        raise Invalid("sync root must be the actual Git worktree root")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        raise Invalid("Git common directory must be absolute")
    no_links(common)
    if not common.is_dir():
        raise Invalid("Git common directory must be a directory")
    backup = common / "apo-skill-sync" / uuid.uuid4().hex
    no_links(backup)
    volume = storage_volume(common)
    for dest, _, _ in destinations:
        if storage_volume(dest) != volume or storage_volume(dest.parent) != volume:
            raise Invalid("cross-volume skill recovery is unsupported; no targets changed")
    backup.mkdir(parents=True)
    prepared = []
    swapped = []
    manifest = {"plan_id": plan_id, "state": "preparing", "entries": []}
    journal_path = backup / "manifest.json"
    journal_path.write_text("{}", encoding="utf-8")

    def journal():
        replace_text(journal_path, json.dumps(manifest, indent=2))

    try:
        for dest, old, old_layout in destinations:
            dest.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".apo-sync-", dir=dest.parent))
            prepared.append((dest, stage, old, old_layout))
            manifest["entries"].append({"target": str(dest), "saved": str(backup / str(len(prepared)-1)),
                                        "existed": old is not None, "staging": str(stage),
                                        "failed_new": str(backup / ("failed-new-" + str(len(prepared)-1))),
                                        "state": "staged"})
            journal()  # Also record each staging path before populating it.
            materialize(stage, original, source_layout)
        manifest["state"] = "staged"
        journal()  # Persist recovery locations before the first target move.
        print("RECOVERY: " + str(journal_path), file=sys.stderr, flush=True)
        # Revalidate immediately before any swap (including all tree contents).
        if (regular(root / ".agent-project-ops/project-config") != config or tree(root / ".agents/skills") != original
                or layout(root / ".agents/skills") != source_layout):
            raise Invalid("STALE_PLAN: source/settings changed while staging")
        for dest, stage, old, old_layout in prepared:
            no_links(dest)
            now = {p.relative_to(dest).as_posix(): regular(p) for p in files_below(dest)} if dest.exists() else None
            if now != old or (layout(dest) if now is not None else {}) != old_layout:
                raise Invalid("STALE_PLAN: target changed while staging")
        for i, (dest, stage, old, old_layout) in enumerate(prepared):
            saved = backup / str(i)
            manifest["entries"][i]["state"] = "swapping"
            journal()
            if old is not None:
                dest.rename(saved)
            swapped.append((i, dest, saved, old))
            stage.rename(dest)
            manifest["entries"][i]["state"] = "installed"
            journal()
        manifest["state"] = "applied"
        journal()
        print("APPLIED: selected skill copies match; recovery=" + str(backup))
        print("Recovery: move the current target aside, then move its saved numbered tree back; see manifest.json")
    except Exception:
        print("FAILED: recovery=" + str(backup), file=sys.stderr)
        # Preserve both versions, including newly staged files, on any failure.
        for i, dest, saved, old in reversed(swapped):
            try:
                if dest.exists():
                    dest.rename(backup / ("failed-new-" + str(i)))
                if old is not None and saved.exists():
                    saved.rename(dest)
                manifest["entries"][i]["state"] = "rolled-back"
            except OSError as rollback_error:
                manifest["entries"][i]["state"] = "recovery-required"
                print("ROLLBACK FAILED: " + str(rollback_error), file=sys.stderr)
        manifest["state"] = "failed"
        try:
            journal()
        except OSError as journal_error:
            print("RECOVERY JOURNAL FAILED: " + str(journal_error), file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("select", "generate", "check", "check-core", "validate-config", "migrate-claude", "sync-skills"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path)
    parser.add_argument("--process-mode", default="")
    parser.add_argument("--agent-tools", default="")
    parser.add_argument("--external-tools", default="")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-plan", default="")
    args = parser.parse_args()
    try:
        root = sync_root(args.root) if args.command == "sync-skills" else args.root.resolve()
        source = args.source.resolve() if args.source else methodology(root)
        if args.command == "sync-skills":
            sync_skills(root, args.apply, args.expect_plan)
        elif args.command == "migrate-claude":
            migrate(root, args.apply)
        elif args.command in ("select", "generate"):
            data = catalog(source)
            values = [args.process_mode, args.agent_tools, args.external_tools]
            prompts = ["Process mode [standard]: ", "Agent tools (" + ",".join(data["agent_tools"]) + "): ",
                       "External tools (" + ",".join(data["external_tools"]) + ",none) [none]: "]
            for i, value in enumerate(values):
                if not value:
                    if args.non_interactive or not sys.stdin.isatty():
                        raise Invalid("explicit --" + KEYS[i].replace("_", "-") + " is required without interactive input")
                    print(prompts[i], file=sys.stderr, end="", flush=True)
                    values[i] = input().strip() or ("standard" if i == 0 else "none" if i == 2 else "")
            settings = normalize(data, *values)
            if args.command == "select":
                print(settings_text(settings), end="")
            else:
                generate(root, source, settings)
                check(root)
        elif args.command == "check":
            check(root)
        elif args.command == "check-core":
            check_core(root)
        elif args.command == "validate-config":
            checked_settings(root, catalog(source))
        return 0
    except (OSError, ValueError, KeyError, EOFError, subprocess.SubprocessError) as exc:
        print("project-settings: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
