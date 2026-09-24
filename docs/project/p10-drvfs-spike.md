# P10 DrvFs spike — `renameat2` EINVAL

**Verdict:** `SUPPORT_WITH_LIMITS`

**Phase:** [#30](https://github.com/Dylan5237/safe-delete-cli/issues/30)
**Baseline read:** `main` @ `d27e1b787b29310903dfc2dbb56b5fa083852a3b`
**Spike time:** `2026-09-24T02:53:41Z`
**Status:** evidence for the Freeze proposal in
[p10-drvfs-freeze.md](p10-drvfs-freeze.md). This note does not implement the
fallback, does not `FREEZE ACK`, and does not `PHASE ACCEPT`.

The cloud VM has no DrvFs mount. Dylan's host note on Issue #30 is the only
DrvFs runtime evidence. This spike confirms the product code path and runs the
same `renameat2` call on the VM's overlay filesystem, then states the WSL host
matrix the implement phase must capture before Accept.

## 1. What Issue #30 already recorded (Dylan host, 2026-09-24)

1. Default root on the WSL Linux filesystem plus a target under `/mnt/c` fails
   closed with `cross_device`. That matches the frozen same-filesystem rule.
2. A same-volume root under `/mnt/c/.../safe-delete` fails with
   `storage_failure` and errno 22. `renameat2(..., RENAME_NOREPLACE)` returns
   `EINVAL`. Plain `os.rename` moves the object.
3. `safe_delete/move.py` treats only `ENOSYS`, `EOPNOTSUPP`, and `ENOTSUP` as
   "primitive unavailable". `EINVAL` is raised and becomes `storage_failure`.
4. `docs/project/p7-agent-usage.md` still marks `/mnt/c` unverified, including
   `fcntl` locking on 9P/DrvFs.

This spike does not re-run (1) or (2). It checks that (3) is still true on
this baseline and that a non-DrvFs Linux filesystem does not need the fallback.

## 2. Code path on this baseline

`safe_delete/move.py` `_renameat2_noreplace` calls libc `renameat2` with flag
`RENAME_NOREPLACE` (`1`) only. On success it returns true. Errnos `ENOSYS`,
`EOPNOTSUPP`, and `ENOTSUP` return the unavailable sentinel. Every other errno,
including `EINVAL` (22), is `raise OSError`.

`atomic_move` turns that unavailable sentinel into `storage_failure` ("safe
no-replace atomic move primitive is unavailable"). It does **not** call
`os.rename`. Other `OSError`s map as follows:

| errno | `errors[].code` | exit |
| --- | --- | --- |
| `EXDEV` | `cross_device` | 2 |
| `EEXIST` | caller `destination_error_code` | that code's category |
| `ENOENT` | `source_not_found` | 2 |
| anything else, including `EINVAL` | `storage_failure` (details keep `errno`) | 4 |

`add` holds `fcntl.flock(..., LOCK_EX)` on `locks/ledger.lock` around
`atomic_move` (`safe_delete/cli.py`). The move helper does not take the lock
itself. `add` pre-checks `same_filesystem` via `st_dev` and uses
`destination_error_code="entry_id_collision"`. Restore uses the default
`destination_exists`. The object directory is `mkdir`'d exclusively before the
payload rename (`safe_delete/ledger.py`).

`docs/architecture/freeze.md` already says the default move is an atomic
same-filesystem rename, copy/delete is not authorized, and where the platform
cannot do an atomic no-replace rename the implementation must document and test
the residual check/rename race and must not intentionally overwrite. It also
says an unavailable atomic primitive fails closed. Those two sentences are why
this phase must scope any fallback to the filesystem that rejects the flag,
and must not globally replace `RENAME_NOREPLACE` with `rename`.

No error-code string in `safe_delete/errors.py` names DrvFs. No selector name
needs to change.

## 3. Cloud VM probe (no DrvFs)

Host: `Linux cursor 6.12.94+ #1 SMP PREEMPT_DYNAMIC` `x86_64`, CPython 3.12.3.
`/mnt` exists and is empty. `/proc/mounts` has no `9p` and no `drvfs`. The
probe directory's `statfs` `f_type` was `0x794c7630` (`OVERLAYFS_SUPER_MAGIC`),
not `V9FS_MAGIC` (`0x01021997`).

The probe used the same libc signature as `safe_delete/move.py`
(`renameat2(int, char*, int, char*, unsigned)` via `ctypes`, `use_errno=True`).

| Call | Result |
| --- | --- |
| `renameat2(..., RENAME_NOREPLACE)` onto an existing file | `rc=-1`, errno `17` `EEXIST`. Source bytes unchanged. Destination bytes unchanged. |
| `renameat2(..., RENAME_NOREPLACE)` of a regular file onto a missing name | `rc=0`. Source name gone. Destination text is the source payload. |
| same, for a symlink | `rc=0`. Destination is a symlink with the original target. |
| same, for a directory | `rc=0`. Child file content preserved. |
| `renameat2` with flag `0x80000000` | `rc=-1`, errno `22` `EINVAL`. Source remains. `EINVAL` is **not** in `{ENOSYS, EOPNOTSUPP, ENOTSUP}`. |
| `renameat2` with flags `0` of that surviving file | `rc=0`. |
| second process `fcntl.flock(LOCK_EX\|LOCK_NB)` while the first holds `LOCK_EX` on this overlay | `second_lock_blocked` (exit 0). |

On this libc, `ENOTSUP` and `EOPNOTSUPP` are the same value `95`. `ENOSYS` is
`38`. The product set therefore has two distinct numbers, and `EINVAL` `22` is
outside it. An `EINVAL` from `renameat2` on overlay becomes `OSError` and, in
the product, `storage_failure`. That is the behavior to keep for every
filesystem whose `f_type` is not 9p.

## 4. Why a scoped fallback can stay a rename

DrvFs on WSL2 is a 9p mount (`f_type` `0x01021997` on hosts where that is
true). `renameat2` with a non-zero flag is the operation Issue #30 saw return
`EINVAL`. `rename` / `renameat` with flags `0` is still one same-filesystem
directory operation: the kernel moves the name. It is not `shutil` copy, not
copy-then-unlink, and not `linkat` plus `unlink`.

`rename` without `RENAME_NOREPLACE` can replace an existing non-directory.
That is the limit. The product already `lstat`s the destination with
`follow_symlinks=False` before the call. The fallback must `lstat` again and,
if the name exists, return the caller's collision code **without** calling
`rename`. The remaining window is the check/rename race against a writer that
does not hold `locks/ledger.lock`. Exclusive `flock` already serializes
safe-delete transactions with each other. It does not serialize arbitrary
same-UID writers. This phase must name that residual. It must not describe it
as a change to Exception #12.

Two host facts are **not** proven here and are implement gates:

- `st_dev` / `st_ino` stable across a flags-0 rename on DrvFs. `atomic_move`
  compares both after the move when the caller passed an expected stat (`add`
  and `restore` do). A 9p server that mints a new inode on rename would fail
  that check **after** the name had moved.
- `fcntl.flock(LOCK_EX)` on a `ledger.lock` that lives on DrvFs actually
  excludes a second WSL process. The overlay probe above only shows exclusion
  on this VM.

If either gate fails on the WSL host, do not ship the fallback and do not
relax the inode check inside this phase. Post `BLOCKED:` on Issue #30.

## 5. WSL host matrix (not run in this spike)

Run on WSL, POSIX `python3`, as the same user the CLI uses. Use a disposable
directory whose final component is `safe-delete` on the Windows drive, and a
second path on the WSL home filesystem. Record `uname -a`, `findmnt -T` for
both, and `statfs` `f_type`.

| # | Setup | Expected observation |
| --- | --- | --- |
| H1 | `statfs` of `/mnt/c` (and `/mnt/d` if mounted) | `f_type == 0x01021997` or the matrix stops and the magic gate is wrong |
| H2 | `renameat2(..., RENAME_NOREPLACE=1)` file, empty dest, parent fds, on that drive | errno `22` `EINVAL` (or, if the kernel differs, `ENOSYS` 38 or `EOPNOTSUPP` 95). Source unchanged. |
| H3 | flags `0` `renameat` / `os.rename` of a file, a directory, and a symlink on that drive | success; kind preserved; record `st_dev` and `st_ino` before and after |
| H4 | H3 inode row | both numbers unchanged for each kind, or **stop** (gate) |
| H5 | two processes, `LOCK_EX` then `LOCK_EX\|LOCK_NB` on `<root>/locks/ledger.lock` on that drive | second call raises `BlockingIOError`, or **stop** (gate) |
| H6 | default home root, source on `/mnt/c` | `cross_device`, exit 2, source unchanged |
| H7 | root final component `safe-delete` on `/mnt/c`, source on that same `st_dev` | after implement: `add` exit 0; before implement: today's `storage_failure` errno 22 |
| H8 | destination name already present | collision code (`entry_id_collision` on add, `destination_exists` on restore), source bytes unchanged |
| H9 | `\\wsl$\...` hook cwd, native Windows `python.exe` | unchanged deny / `unsupported platform` — do not port |

## 6. Decision this spike supports

Support same-volume 9p/DrvFs roots and targets by falling back from
`renameat2(RENAME_NOREPLACE)` to flags-0 `renameat` only when `f_type` is
`V9FS_MAGIC` and the errno is the unsupported-flag class (`EINVAL`, plus
`ENOSYS` / `EOPNOTSUPP` / `ENOTSUP` so a kernel that uses the usual unsupported
errno does not hard-fail). Keep every other filesystem on today's fail-closed
path. Do not copy. Details, flags, and codes are the Freeze proposal.
