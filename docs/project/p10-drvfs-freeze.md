# P10 DrvFs /mnt — CONTRACT FREEZE PROPOSAL

**Status:** `freeze:pending` — proposal only. No `FREEZE ACK`, no `PHASE ACCEPT`,
no Phase PASS, and no product behavior change. No `feat/` or `fix/` branch is
authorized until `@Dylan5237` records `FREEZE ACK` on
[Issue #30](https://github.com/Dylan5237/safe-delete-cli/issues/30).

**Phase Issue:** [#30](https://github.com/Dylan5237/safe-delete-cli/issues/30) ·
**Command Center:** [#1](https://github.com/Dylan5237/safe-delete-cli/issues/1)

**Baseline:** `main @ d27e1b787b29310903dfc2dbb56b5fa083852a3b` (P9 WorkBuddy
merged via PR #29). Current-behavior statements were read from that tree.

**Spike:** [p10-drvfs-spike.md](p10-drvfs-spike.md). Verdict
`SUPPORT_WITH_LIMITS`. The cloud VM had no DrvFs; the WSL host matrix in that
note is an implement gate, not a reason to deny in this proposal.

**Review artifact:** the docs PR opened from `docs/30-p10-drvfs-freeze`.

**Disposer:** `@Dylan5237`. The author of this proposal must not ACK it, merge
it into a Phase PASS, or start the implement branch on their own authority.

**Subordinate documents (unchanged by this proposal):**
[docs/architecture/freeze.md](../architecture/freeze.md),
[docs/architecture/exceptions.md](../architecture/exceptions.md),
[docs/project/p7-agent-usage.md](p7-agent-usage.md),
[skills/safe-delete/SKILL.md](../../skills/safe-delete/SKILL.md).
Implement, after ACK, edits the agent/doctor wording specified in § 4. It does
not reopen P0–P9 contracts except for the scoped move rule in § 3.

**Decided stance:** `SUPPORT_WITH_LIMITS`. Same-volume DrvFs (Linux 9p magic
`0x01021997`) may move with flags-0 `renameat` when `renameat2(RENAME_NOREPLACE)`
returns the unsupported-flag errno class. Cross-device stays `cross_device`.
No copy-based trash.

---

## 1. Goal and boundaries

### 1.1 Core problem (one phase, one problem)

`safe-delete add` of a path on WSL DrvFs (`/mnt/c`, `/mnt/d`, …) is unusable
when the trash root is on that same volume, because `renameat2` with
`RENAME_NOREPLACE` returns `EINVAL` and the CLI turns that into
`storage_failure`. The default root on the WSL home filesystem already fails
closed with `cross_device`, which is correct and stays. This phase decides the
same-volume case and the agent wording so operators do not invent a `/mnt`
root to dodge `cross_device`.

### 1.2 Goals

| # | Goal | Blocking for P10 ACCEPT |
| --- | --- | --- |
| G1 | Same-volume 9p/DrvFs `add` / `restore` / rollback move succeeds by atomic rename, not copy, for file, directory, and symlink. | **yes** |
| G2 | `EINVAL` (and the unsupported-flag errnos below) fall back to flags-0 `renameat` only when destination `f_type` is `V9FS_MAGIC`. Every other filesystem keeps today's fail-closed `EINVAL` path. | **yes** |
| G3 | No intentional overwrite. Collision codes stay the existing vocabulary. | **yes** |
| G4 | Agent skill, `p7-agent-usage.md`, and `doctor` state the limit. `needs_attention: false` is not a `RENAME_NOREPLACE` claim. | **yes** |
| G5 | WSL host matrix H1–H8 in the spike, including inode stability and `flock` exclusion. | **yes** — evidence gate. Failure of H4 or H5 stops the fallback; do not weaken checks in this phase. |

### 1.3 Non-goals (binding)

- Native Windows Python, `msvcrt`, Win32 locks, or a `python.exe` port.
- App, GUI, tray, dashboard, or web viewer.
- NTFS quarantine scripts, or any Windows-side recycle-bin product.
- Exception #12. This phase does not retie, expand, reinterpret, or claim to
  fix same-UID staging publication. The DrvFs check/rename residual is a
  separate sentence (§ 3.4).
- Copy, copy-then-delete, `shutil`, `sendfile`, or `linkat`+`unlink` trash.
- A new public selector, alias, or product name. Selectors stay `claude`,
  `cursor`, `workbuddy`, `path-shim` (`rm-shim` alias, `setup path` spelling).
  No `codebuddy` user-facing name.
- A storage directory whose final component is anything other than
  `safe-delete`. No `-store` suffix and no second canonical basename.
- Changing `\\wsl$\...` hook denial.
- Global replacement of `RENAME_NOREPLACE` on ext4, xfs, btrfs, overlay, or
  macOS.
- Proving Windows-side lock coherence with DrvFs. In-WSL `flock` exclusion is
  in scope as a gate; cross-OS byte-range locks are not.

---

## 2. Current baseline

Read from `main @ d27e1b787b29310903dfc2dbb56b5fa083852a3b`.

| Surface | Current behavior | P10 delta |
| --- | --- | --- |
| `renameat2` flag | `RENAME_NOREPLACE` = `1` only | unchanged first attempt |
| Fallback errnos | `ENOSYS`, `EOPNOTSUPP`, `ENOTSUP` → unavailable → `storage_failure`. `EINVAL` → `storage_failure` with `errno` | on 9p only, that class falls through to flags-0 `renameat` (§ 3) |
| Home root + `/mnt/c` source | `cross_device`, exit 2, source unchanged | unchanged |
| `/mnt/*` docs | Unverified (`p7-agent-usage.md` § 6) | after implement, the § 4 wording |
| Ledger lock | `fcntl.flock` `LOCK_EX` around add/restore mutations | unchanged protocol |
| Error vocabulary | frozen `snake_case` set | no new code |
| Root basename | final component `safe-delete` | unchanged |

---

## 3. Move contract (proposed)

### 3.1 Filesystem gate

Read `f_type` with `fstatfs` on the **destination parent directory fd** already
opened for the move (no extra path walk).

```text
V9FS_MAGIC = 0x01021997
```

The fallback in § 3.3 runs only when that `f_type` equals `V9FS_MAGIC`.
WSL DrvFs is this magic. Any other 9p mount with the same magic gets the same
rule, because the trigger is the filesystem that rejects the flag, not the
`/mnt/` prefix. A path under `/mnt` whose `f_type` is not `V9FS_MAGIC` does
not get the fallback.

`st_dev` inequality stays `cross_device` (exit 2) before `renameat2`, including
WSL ext4 home versus `/mnt/c`. The source is left unchanged. No copy.

### 3.2 Flags

1. First call, all Linux filesystems, unchanged:
   `renameat2(source_parent_fd, source_name, destination_parent_fd, destination_name, 1)`
   where `1` is `RENAME_NOREPLACE`.
2. Return `0`: done. Post-move `st_dev` / `st_ino` / kind checks stay as they
   are today.
3. Fallback call, **9p only** and only after § 3.3's `lstat`:
   `os.rename(source_name, destination_name, src_dir_fd=source_parent_fd, dst_dir_fd=destination_parent_fd)`
   which is `renameat` with **flags 0**.
4. Forbidden on the fallback: `RENAME_NOREPLACE` (`1`) again, `RENAME_EXCHANGE`
   (`2`), `RENAME_WHITEOUT` (`4`), any other non-zero flag, `linkat`,
   `unlink`, and any userspace copy.

### 3.3 Errno class and failure codes

From the `renameat2` call in § 3.2 step 1:

| errno | value on this glibc | 9p (`V9FS_MAGIC`) | any other `f_type` |
| --- | --- | --- | --- |
| `EINVAL` | 22 | § 3.3 fallback | `storage_failure`, details `errno=22`, exit 4. Source unchanged. |
| `ENOSYS` | 38 | § 3.3 fallback | today's unavailable → `storage_failure`, exit 4 |
| `EOPNOTSUPP` and `ENOTSUP` | 95 (same on Linux) | § 3.3 fallback | today's unavailable → `storage_failure`, exit 4 |
| `EEXIST` | 17 | no fallback. Caller collision code (§ 3.5) | unchanged |
| `EXDEV` | 18 | no fallback. `cross_device`, exit 2 | unchanged |
| `ENOENT` | 2 | no fallback. `source_not_found`, exit 2 | unchanged |
| any other | | no fallback. `storage_failure` with `errno`, exit 4 | unchanged |

`EINVAL` is in the 9p fallback set because Issue #30 observed it and because
`rename(2)` uses `EINVAL` when the filesystem rejects a flag. The other three
stay in that set **only on 9p** so a kernel that reports the ordinary
"operation not supported" errno takes the same rename. They do **not** start
falling back to `os.rename` on ext4, overlay, or any non-9p filesystem. The
cloud VM probe showed overlay `RENAME_NOREPLACE` succeeds, and a bogus flag's
`EINVAL` is outside today's fallback set; that non-9p `EINVAL` behavior stays.

Fallback sequence, and only then:

1. `lstat` the destination name on `destination_parent_fd` with
   `follow_symlinks=False`.
2. If the name exists (including a dangling symlink): do **not** rename.
   Raise the caller `destination_error_code` (§ 3.5). Source unchanged.
3. If the name is absent: flags-0 `renameat` as in § 3.2 step 3.
4. If that `renameat` raises: map `EXDEV` → `cross_device`, `EEXIST` →
   `destination_error_code`, `ENOENT` → `source_not_found`, anything else →
   `storage_failure` with `errno`. Do not retry with a copy.
5. On success, the existing post-move `st_dev`, `st_ino`, and kind checks run
   unchanged. A mismatch is `storage_failure`. Implement must not delete or
   loosen those checks to "make DrvFs pass".

No new `errors[].code` string. `FROZEN_ERROR_CODES` stays the current set.

### 3.4 Locking and the residual race

The fallback is legal only on call paths that already hold
`fcntl.flock(LOCK_EX)` on `<root>/locks/ledger.lock` for the whole
move/append transaction (`add`, `restore`, and their rollbacks). The fallback
does not acquire a second lock and does not run from a lock-free helper.

`flock` failure stays `ledger_failure` (exit 4) with no move.

Residual, to be written verbatim in doctor and the skill (§ 4):

```text
DrvFs/9p root: same-filesystem rename uses renameat (flags 0) after lstat because renameat2(RENAME_NOREPLACE) is not supported. Atomic rename, not a copy. Check/rename race remains. Not an Exception #12 change.
```

That race is: a writer that does not hold the ledger lock creates the
destination name after `lstat` and before flags-0 `renameat`, and `rename`
replaces a non-directory. Safe-delete processes are serialized by `LOCK_EX`.
This sentence does not claim the race is closed and does not amend Exception
#12.

### 3.5 Collision codes (unchanged callers)

| Caller | `destination_error_code` | exit |
| --- | --- | --- |
| `add` payload name inside the exclusively created entry directory | `entry_id_collision` | 3 |
| `restore` destination | `destination_exists` | 3 |
| rollback moves | the code those call sites already pass (`destination_exists` unless a call site passes another existing code) | that code's category |

### 3.6 Root name

The final path component of the storage root remains exactly `safe-delete`
(default `~/.local/share/safe-delete`, or an explicit `--root` /
`SAFE_DELETE_ROOT` whose final component is `safe-delete`). A supported DrvFs
root looks like `/mnt/<drive>/<parents>/safe-delete` and serves only paths
with the same `st_dev`. Agents must not invent a different basename.

### 3.7 Implement gates from the spike matrix

Before the implement PR is eligible for review as complete, the WSL host log
must include spike rows H1–H8.

- H4 (`st_ino` and `st_dev` stable across flags-0 rename for file, directory,
  and symlink) failing → do not ship the fallback. Comment `BLOCKED:` on
  Issue #30. Do not relax the post-move identity check in this phase.
- H5 (second `LOCK_EX|LOCK_NB` blocked on the DrvFs `ledger.lock`) failing →
  same `BLOCKED:` stop. Do not advertise the root as lock-equivalent to ext4.

Those stops are fail-closed. They are not permission to switch this phase to
copy-based trash.

---

## 4. Wording implement must land (not in this PR)

### 4.1 `docs/project/p7-agent-usage.md` § 6, `/mnt/c` row

Replace the "Unverified configuration" row with:

- `/home/...` source and root: supported, unchanged.
- Source on `/mnt/<drive>` and root on a different `st_dev` (the usual WSL
  home root): `cross_device`, exit 2. Do not copy. Do not `rm`. Do not point
  `--root` at `/mnt` to bypass that unless the root's final component is
  `safe-delete` **and** the source is on that same drive.
- Same-drive root `.../safe-delete`: supported with the § 3.4 residual.
  `doctor` / `hook status` `enforced: true` is only the registered hook
  boundary. It is not proof of `RENAME_NOREPLACE` and not proof of Windows-side
  locking.
- `\\wsl$\...`: still denied.

### 4.2 `skills/safe-delete/SKILL.md`

Add the same rule under Platform, in agent language: never invent `--root`
under `/mnt` for a cross-device source; a same-drive `safe-delete` root is the
supported shape; read `errors[].code` (`cross_device` versus success); the
§ 3.4 residual is not Exception #12.

### 4.3 `doctor`

When the resolved root's destination-parent `f_type` is `V9FS_MAGIC`, JSON
gains two additive fields on the existing storage object:

| field | value |
| --- | --- |
| `storage.filesystem` | `v9fs` |
| `storage.noreplace` | `emulated` |
| `storage.noreplace_residual` | the verbatim § 3.4 sentence |

Non-9p roots use `storage.noreplace` = `native` and omit the residual (or set
it null). This phase does not set `needs_attention` true solely because the
root is 9p. `doctor` stays read-only: the probe is `fstatfs` only, no write,
no trial rename.

Human `doctor` prints the same residual sentence when `noreplace` is
`emulated`.

---

## 5. Success criteria (implement phase)

| ID | Criterion | Proof |
| --- | --- | --- |
| S1 | File, directory, and symlink `add` into a same-`st_dev` 9p root whose final component is `safe-delete` exits 0. Payload kind matches. `st_dev` and `st_ino` match the pre-move stat. | WSL host log (spike H3, H4, H7) plus a unit test that simulates 9p `EINVAL` then flags-0 rename |
| S2 | Occupied destination is not renamed over. `add` returns `entry_id_collision`; `restore` returns `destination_exists`. Source bytes unchanged. | unit test and spike H8 |
| S3 | Non-9p `EINVAL` from `renameat2` is still `storage_failure` exit 4 with `errno` 22. No `os.rename`. | unit test on a non-9p double; cloud VM overlay remains a legal place to run it |
| S4 | Different `st_dev` (WSL home root, `/mnt/c` source) is still `cross_device` exit 2. Source unchanged. No copy. | host log H6 and existing cross-device test |
| S5 | Second process cannot take `LOCK_EX` non-blocking while the first holds the DrvFs ledger lock. `flock` failure is still `ledger_failure`. | host log H5 |
| S6 | `FROZEN_ERROR_CODES` gains no DrvFs-specific string. | diff of `safe_delete/errors.py` |
| S7 | Skill, `p7-agent-usage.md`, and `doctor` match § 4, including the verbatim residual. `needs_attention` is not true only because the root is 9p. | doc/JSON test |
| S8 | Fallback implementation contains no copy, `linkat`/`unlink` emulation, or non-zero rename flag. | review of `safe_delete/move.py` |
| S9 | Public selectors and the `safe-delete` root basename are unchanged. | review |
| S10 | Diff does not add native Windows, an App, an NTFS quarantine tool, or an Exception #12 edit. | review |
| S11 | H4 or H5 red → no fallback shipped; Issue #30 carries `BLOCKED:` and this phase is not proposed `PHASE ACCEPT`. | issue comment |

---

## 6. Risks

- 9p inode numbers that change across `rename` would trip the post-move check
  after a successful rename. § 3.7 stops the phase rather than dropping the
  check.
- `flock` on DrvFs may succeed without excluding. § 3.7 treats a failed H5 as
  `BLOCKED`, not as support.
- `EINVAL` is also used for "invalid rename" (for example a directory into
  itself). Those calls are rare on the trash path. On 9p the fallback `renameat`
  returns the same `EINVAL` and still maps to `storage_failure`. On non-9p,
  `EINVAL` never reaches `renameat`.
- A concurrent same-UID writer can still win the check/rename window. The
  residual sentence is the contract. It is not closed by this phase.

---

## 7. Process

1. This document is the Freeze proposal (`CONTRACT FREEZE` pending disposer
   `FREEZE ACK` on Issue #30).
2. After ACK, one implement worktree and one `feat/30-...` PR. Tests that are
   code live on that PR. The WSL host log lives on an `evidence/30-...` PR or
   an Issue proof comment, not mixed into the feature diff as the only proof.
3. Agent may propose `EVIDENCE READY`. Only `@Dylan5237` writes `PHASE ACCEPT`.
4. Merging either PR is not Phase PASS.

## Freeze log

- [x] Contract written (this file), dated 2026-09-24
- [ ] Disposer comment: `FREEZE ACK` + date
- [x] No `feat/` / `fix/` branch in this proposal
