"""Safe restore transaction for one active P2 ledger entry."""

from __future__ import annotations

import errno
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .audit import LedgerEntry
from .errors import SafeDeleteError, error
from .ledger import append_event, build_restore_record, metadata_for_record
from .move import atomic_move, rename_without_replace
from .storage import (
    Layout,
    ensure_safe_target,
    is_exdev,
    open_directory_without_symlinks,
)


@dataclass
class _CreatedParent:
    """A parent component created by this invocation, tracked to a safe end.

    ``parent_fd`` pins the directory the component is published into (the
    existing anchor for the first created component, the staged parent for
    deeper ones); ``dir_fd`` pins the created directory itself so its inode
    cannot be recycled while identity checks rely on it.  ``staged_name`` is
    the private staging name of the first created component until publish.
    """

    path: Path
    name: str
    parent_fd: int | None
    dir_fd: int | None
    identity: tuple[int, int] | None
    staged_name: str | None = None
    published: bool = False


def _before_publish_hook(parent_fd: int, name: str) -> None:
    """Adversarial-test seam before the atomic parent publication.

    Fires after the missing parent chain was created inside private staging
    (where its creation-time identity is bound beyond substitution) and
    immediately before the single no-replace rename that publishes it at
    ``name`` — the only window in which an adversary can occupy the name.
    Production behavior is a no-op.
    """

    return None


def _before_cleanup_reclaim_hook(parent_fd: int, name: str) -> None:
    """Adversarial-test seam before rollback cleanup reclaims a parent.

    Fires after cleanup resolved the creation-time identity record for
    ``name`` and immediately before the reclaim rename that precedes any
    removal — the analog of the historical identity-check-to-rmdir window.
    Production behavior is a no-op.
    """

    return None


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(stat_result: os.stat_result) -> tuple[int, int]:
    return stat_result.st_dev, stat_result.st_ino


def _same_identity(
    left: os.stat_result | tuple[int, int],
    right: os.stat_result | tuple[int, int],
) -> bool:
    left_identity = _identity(left) if isinstance(left, os.stat_result) else left
    right_identity = _identity(right) if isinstance(right, os.stat_result) else right
    return left_identity == right_identity


def _staged_name() -> str:
    return f".safe-delete-stage-{uuid.uuid4()}"


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise error(
            "storage_failure",
            "safe restore parent descriptors are unavailable on this platform",
        )
    return flags


def _parent_cleanup_error(
    parent: _CreatedParent,
    reason: str,
    *,
    actual: os.stat_result | None = None,
    exc: OSError | None = None,
) -> SafeDeleteError:
    details: dict[str, object] = {
        "path": str(parent.path),
        "preserved": True,
        "reason": reason,
    }
    if parent.identity is not None:
        details["expected_device"] = parent.identity[0]
        details["expected_inode"] = parent.identity[1]
    if actual is not None:
        details["actual_device"] = actual.st_dev
        details["actual_inode"] = actual.st_ino
    if exc is not None:
        details["errno"] = exc.errno
    return error(
        "storage_failure",
        "cannot verify restore parent identity; preserving directory",
        **details,
    )


def _close_created_parent_descriptors(created: list[_CreatedParent]) -> None:
    for parent in created:
        for attribute in ("parent_fd", "dir_fd"):
            descriptor = getattr(parent, attribute)
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
            setattr(parent, attribute, None)


def _discard_unpublished_parent(
    parent: _CreatedParent,
    staging_fd: int | None,
) -> SafeDeleteError | None:
    """Remove a never-published staged directory from private staging."""

    if parent.staged_name is not None:
        target_fd, target_name = staging_fd, parent.staged_name
    else:
        target_fd, target_name = parent.parent_fd, parent.name
    if target_fd is None or target_name is None:
        return _parent_cleanup_error(parent, "staged parent descriptors unavailable")
    try:
        os.rmdir(target_name, dir_fd=target_fd)
    except OSError as exc:
        if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
            # Data placed inside after creation is preserved without treating
            # it as an identity race, matching the published-path rule.
            return None
        return _parent_cleanup_error(
            parent,
            "staged directory could not be discarded",
            exc=exc,
        )
    return None


def _reclaim_published_parent(
    parent: _CreatedParent,
    staging_fd: int | None,
) -> SafeDeleteError | None:
    """Remove a published created parent only after proving it is ours.

    The destination-tree name is first reclaimed into private staging by a
    no-replace rename.  Only an object whose identity matches the
    creation-time inode (still pinned by the held descriptor, so it cannot
    have been recycled) is removed, and the removal happens inside private
    staging where the name cannot be swapped.  A replacement found at the
    name is put back untouched and reported as preserved.
    """

    if staging_fd is None or parent.parent_fd is None or parent.identity is None:
        return _parent_cleanup_error(parent, "created parent descriptors unavailable")
    _before_cleanup_reclaim_hook(parent.parent_fd, parent.name)
    reclaim_name = _staged_name()
    try:
        rename_without_replace(parent.parent_fd, parent.name, staging_fd, reclaim_name)
    except FileNotFoundError:
        return _parent_cleanup_error(parent, "directory disappeared before cleanup")
    except FileExistsError:
        return _parent_cleanup_error(parent, "cleanup staging name collision")
    except SafeDeleteError:
        return _parent_cleanup_error(
            parent,
            "safe no-replace rename is unavailable for cleanup",
        )
    except OSError as exc:
        return _parent_cleanup_error(
            parent,
            "cannot reclaim directory before cleanup",
            exc=exc,
        )

    flags = _directory_flags()
    try:
        reclaimed_fd = os.open(reclaim_name, flags, dir_fd=staging_fd)
    except OSError as exc:
        return _parent_cleanup_error(
            parent,
            "cannot inspect reclaimed directory before cleanup",
            exc=exc,
        )
    try:
        try:
            reclaimed_stat = os.fstat(reclaimed_fd)
        except OSError as exc:
            return _parent_cleanup_error(
                parent,
                "cannot verify reclaimed directory before cleanup",
                exc=exc,
            )
        if not stat.S_ISDIR(reclaimed_stat.st_mode) or not _same_identity(
            reclaimed_stat,
            parent.identity,
        ):
            try:
                rename_without_replace(
                    staging_fd,
                    reclaim_name,
                    parent.parent_fd,
                    parent.name,
                )
            except SafeDeleteError:
                return _parent_cleanup_error(
                    parent,
                    "replacement directory preserved in staging",
                    actual=reclaimed_stat,
                )
            except OSError as exc:
                return _parent_cleanup_error(
                    parent,
                    "replacement directory preserved in staging",
                    actual=reclaimed_stat,
                    exc=exc,
                )
            return _parent_cleanup_error(
                parent,
                "directory was replaced before cleanup",
                actual=reclaimed_stat,
            )
        try:
            os.rmdir(reclaim_name, dir_fd=staging_fd)
        except OSError as exc:
            if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                # Our directory holds data added after creation (for example a
                # deeper component whose cleanup was already preserved).  Put
                # it back and preserve it, matching the historical non-error
                # cleanup rule for non-empty created parents.
                try:
                    rename_without_replace(
                        staging_fd,
                        reclaim_name,
                        parent.parent_fd,
                        parent.name,
                    )
                except (OSError, SafeDeleteError):
                    return _parent_cleanup_error(
                        parent,
                        "non-empty created directory preserved in staging",
                    )
                return None
            return _parent_cleanup_error(
                parent,
                "directory could not be removed after identity verification",
                exc=exc,
            )
        return None
    finally:
        os.close(reclaimed_fd)


def _remove_created_parents(
    created: list[_CreatedParent],
    staging_fd: int | None = None,
) -> SafeDeleteError | None:
    """Remove only directories proven to be this invocation's creates.

    A shared-tree pathname is never removed directly: unpublished staged
    directories are discarded inside private staging, and published
    directories are reclaimed into private staging by rename and removed
    there only when the reclaimed object matches the creation-time identity
    pinned by the held descriptor.  Replacements and unverifiable entries are
    preserved and reported instead of deleted.
    """

    first_error: SafeDeleteError | None = None
    for parent in reversed(created):
        try:
            if parent.published:
                cleanup_error = _reclaim_published_parent(parent, staging_fd)
            else:
                cleanup_error = _discard_unpublished_parent(parent, staging_fd)
            if cleanup_error is not None and first_error is None:
                first_error = cleanup_error
        finally:
            _close_created_parent_descriptors([parent])
    return first_error


def _with_cleanup_error(
    primary: SafeDeleteError,
    cleanup_error: SafeDeleteError,
) -> SafeDeleteError:
    details = {
        **primary.details,
        "cleanup_error": cleanup_error.code,
        "cleanup_path": cleanup_error.details.get("path"),
        "cleanup_preserved": True,
    }
    return SafeDeleteError(primary.code, primary.message, details)


def _cleanup_and_attach(
    primary: SafeDeleteError,
    created: list[_CreatedParent],
    staging_fd: int | None = None,
) -> SafeDeleteError:
    cleanup_error = _remove_created_parents(created, staging_fd)
    if cleanup_error is None:
        return primary
    return _with_cleanup_error(primary, cleanup_error)


def _remember_cleanup_error(exc: BaseException, cleanup_error: SafeDeleteError) -> None:
    # OSError is converted to the stable parent error code by _parent_error;
    # retain the cleanup finding across that conversion without changing the
    # original failure classification.
    try:
        setattr(exc, "_restore_cleanup_error", cleanup_error)
    except (AttributeError, TypeError):
        pass


def _open_staging_directory(layout: Layout) -> int:
    """Open the private restore staging directory, creating it if missing.

    The staging directory lives inside the trash so it always shares the
    trash's filesystem (and therefore the filesystem of every restore
    destination that is not already ``cross_device``).  Mode ``0700`` keeps
    it outside the adversary's reach, which is what makes identities bound
    inside it substitution-proof.
    """

    staging = layout.trash / "staging"
    flags = _directory_flags()
    try:
        trash_fd = open_directory_without_symlinks(layout.trash)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot open trash directory for restore staging: {layout.trash}",
            path=str(staging),
            errno=exc.errno,
        ) from exc
    try:
        try:
            staged_stat = os.stat(staging.name, dir_fd=trash_fd, follow_symlinks=False)
        except FileNotFoundError:
            staged_stat = None
            try:
                os.mkdir(staging.name, 0o700, dir_fd=trash_fd)
            except FileExistsError:
                try:
                    staged_stat = os.stat(
                        staging.name,
                        dir_fd=trash_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise error(
                        "storage_failure",
                        f"cannot inspect restore staging directory: {staging}",
                        path=str(staging),
                        errno=exc.errno,
                    ) from exc
            except OSError as exc:
                raise error(
                    "storage_failure",
                    f"cannot create restore staging directory: {staging}",
                    path=str(staging),
                    errno=exc.errno,
                ) from exc
        if staged_stat is not None and not stat.S_ISDIR(staged_stat.st_mode):
            raise error(
                "storage_failure",
                f"restore staging path is not a directory: {staging}",
                path=str(staging),
            )
        try:
            return os.open(staging.name, flags, dir_fd=trash_fd)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot open restore staging directory: {staging}",
                path=str(staging),
                errno=exc.errno,
            ) from exc
    finally:
        os.close(trash_fd)


def _stage_missing_chain(
    anchor_fd: int,
    staging_fd: int,
    missing_components: tuple[str, ...],
    first_path: Path,
    created: list[_CreatedParent],
) -> int:
    """Create the missing parent chain inside private staging.

    Every component is made, opened, and fstat'd inside the private staging
    directory, so the recorded identity is bound to this invocation's create
    with no substitution window.  Returns the descriptor of the deepest
    staged directory; the chain is published into the destination tree later
    by one atomic no-replace rename of the first created component.
    """

    flags = _directory_flags()
    staged_parent_fd = staging_fd
    staged_name: str | None = _staged_name()
    record_path = first_path
    try:
        for missing in missing_components:
            staged_component = staged_name if staged_name is not None else missing
            try:
                os.mkdir(staged_component, 0o700, dir_fd=staged_parent_fd)
            except OSError as exc:
                raise error(
                    "storage_failure",
                    f"cannot stage restore parent: {record_path}",
                    path=str(record_path),
                    errno=exc.errno,
                ) from exc
            try:
                staged_fd = os.open(staged_component, flags, dir_fd=staged_parent_fd)
                try:
                    staged_stat = os.fstat(staged_fd)
                except OSError:
                    os.close(staged_fd)
                    raise
            except OSError as exc:
                try:
                    os.rmdir(staged_component, dir_fd=staged_parent_fd)
                except OSError:
                    pass
                raise error(
                    "storage_failure",
                    f"cannot inspect staged restore parent: {record_path}",
                    path=str(record_path),
                    errno=exc.errno,
                ) from exc
            if not stat.S_ISDIR(staged_stat.st_mode):
                os.close(staged_fd)
                try:
                    os.rmdir(staged_component, dir_fd=staged_parent_fd)
                except OSError:
                    pass
                raise error(
                    "storage_failure",
                    f"staged restore parent is not a directory: {record_path}",
                    path=str(record_path),
                )
            created.append(
                _CreatedParent(
                    path=record_path,
                    name=missing,
                    parent_fd=(
                        os.dup(anchor_fd)
                        if staged_name is not None
                        else os.dup(staged_parent_fd)
                    ),
                    dir_fd=os.dup(staged_fd),
                    identity=_identity(staged_stat),
                    staged_name=staged_name,
                )
            )
            if staged_parent_fd != staging_fd:
                os.close(staged_parent_fd)
            staged_parent_fd = staged_fd
            staged_name = None
            record_path = record_path / missing
        return staged_parent_fd
    except BaseException:
        if staged_parent_fd != staging_fd:
            try:
                os.close(staged_parent_fd)
            except OSError:
                pass
        raise


def _open_restore_parent(
    parent: Path,
    *,
    create_parents: bool,
    layout: Layout,
) -> tuple[int, list[_CreatedParent], int | None]:
    """Open the destination parent, staging any missing chain privately.

    Existing components are opened once with ``O_NOFOLLOW`` and held, so
    traversal never re-resolves a pathname.  Missing components are created
    inside the private staging directory and returned still staged; the
    caller moves the payload into the staged tree and publishes it with a
    single atomic no-replace rename, so a created parent never appears in the
    shared tree without the payload already inside.
    """

    flags = _directory_flags()
    fd = open_directory_without_symlinks(Path("/"))
    current = Path("/")
    created: list[_CreatedParent] = []
    staging_fd: int | None = None
    try:
        components = Path(os.path.normpath(os.fspath(parent))).parts[1:]
        for index, component in enumerate(components):
            next_path = current / component
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create_parents:
                    raise
                if staging_fd is None:
                    staging_fd = _open_staging_directory(layout)
                deepest_fd = _stage_missing_chain(
                    fd,
                    staging_fd,
                    components[index:],
                    next_path,
                    created,
                )
                os.close(fd)
                return deepest_fd, created, staging_fd
            os.close(fd)
            fd = next_fd
            current = next_path
        return fd, created, staging_fd
    except BaseException as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        cleanup_error = _remove_created_parents(created, staging_fd)
        if staging_fd is not None:
            try:
                os.close(staging_fd)
            except OSError:
                pass
        if cleanup_error is not None:
            _remember_cleanup_error(exc, cleanup_error)
        raise


def _parent_error(exc: BaseException, parent: Path, entry_id: str) -> SafeDeleteError:
    cleanup_error = getattr(exc, "_restore_cleanup_error", None)

    def finish(result: SafeDeleteError) -> SafeDeleteError:
        if isinstance(cleanup_error, SafeDeleteError):
            return _with_cleanup_error(result, cleanup_error)
        return result

    if isinstance(exc, SafeDeleteError):
        return finish(exc)
    if isinstance(exc, FileNotFoundError):
        return finish(error(
            "destination_parent_missing",
            f"restore destination parent is missing: {parent}",
            entry_id=entry_id,
            path=str(parent),
        ))
    if isinstance(exc, OSError) and exc.errno in {errno.ENOTDIR, errno.ELOOP}:
        return finish(error(
            "destination_parent_missing",
            f"restore destination parent is not a real directory: {parent}",
            entry_id=entry_id,
            path=str(parent),
        ))
    if isinstance(exc, OSError):
        return finish(error(
            "storage_failure",
            f"cannot open restore destination parent: {parent}",
            entry_id=entry_id,
            path=str(parent),
            errno=exc.errno,
        ))
    return finish(error(
        "storage_failure",
        f"cannot open restore destination parent: {parent}",
        entry_id=entry_id,
        path=str(parent),
    ))


def _rollback_restore(
    *,
    destination: str,
    payload: str,
    created_parents: list[_CreatedParent],
    append_error: SafeDeleteError,
    destination_parent_fd: int,
    payload_parent_fd: int,
    payload_stat: os.stat_result,
    kind: str,
    staging_fd: int | None,
) -> SafeDeleteError:
    try:
        atomic_move(
            destination,
            payload,
            source_parent_fd=destination_parent_fd,
            destination_parent_fd=payload_parent_fd,
            expected_source_stat=payload_stat,
            expected_source_kind=kind,
        )
    except SafeDeleteError as rollback_error:
        return error(
            "rollback_failed",
            "restore ledger append failed and payload rollback failed",
            restore_path=destination,
            trashed_path=payload,
            append_error=append_error.code,
            rollback_error=rollback_error.code,
        )
    cleanup_error = _remove_created_parents(created_parents, staging_fd)
    if cleanup_error is not None:
        return error(
            "rollback_failed",
            "restore ledger append failed; parent cleanup identity could not be verified",
            restore_path=destination,
            trashed_path=payload,
            append_error=append_error.code,
            cleanup_error=cleanup_error.code,
            cleanup_path=cleanup_error.details.get("path"),
            cleanup_preserved=True,
        )
    return SafeDeleteError(
        append_error.code,
        append_error.message,
        {
            **append_error.details,
            "restore_path": destination,
            "trashed_path": payload,
            "rolled_back": True,
        },
    )


def restore_entry(
    layout: Layout,
    entry: LedgerEntry,
    *,
    restore_path: str | None,
    create_parents: bool,
) -> dict[str, object]:
    """Restore an active entry; the caller must hold the exclusive ledger lock."""

    if restore_path is not None and not restore_path:
        raise error(
            "usage_error",
            "restore destination must not be empty",
            entry_id=entry.entry_id,
        )

    payload = layout.payload(entry.entry_id)
    payload_parent_fd = None
    destination_parent_fd = None
    staging_fd: int | None = None
    created_parents: list[_CreatedParent] = []
    try:
        try:
            payload_parent_fd = open_directory_without_symlinks(payload.parent)
            payload_stat = _lstat_at(payload_parent_fd, payload.name)
        except SafeDeleteError:
            raise
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect trash payload: {payload}",
                entry_id=entry.entry_id,
                trashed_path=str(payload),
                errno=exc.errno,
            ) from exc
        if payload_stat is None:
            raise error(
                "payload_missing",
                "active ledger entry has no payload",
                entry_id=entry.entry_id,
                trashed_path=str(payload),
            )

        destination = entry.original_path if restore_path is None else restore_path
        destination_path = Path(destination)
        ensure_safe_target(layout, destination)
        parent = destination_path.parent
        try:
            destination_parent_fd, created_parents, staging_fd = _open_restore_parent(
                parent,
                create_parents=create_parents,
                layout=layout,
            )
        except BaseException as exc:
            raise _parent_error(exc, parent, entry.entry_id) from exc

        try:
            destination_stat = _lstat_at(destination_parent_fd, destination_path.name)
        except OSError as exc:
            primary = error(
                "storage_failure",
                f"cannot inspect restore destination: {destination}",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            )
            raise _cleanup_and_attach(primary, created_parents, staging_fd) from exc
        if destination_stat is not None:
            primary = error(
                "destination_exists",
                f"restore destination already exists: {destination}",
                entry_id=entry.entry_id,
                path=destination,
            )
            raise _cleanup_and_attach(primary, created_parents, staging_fd)

        try:
            payload_parent_stat = os.fstat(payload_parent_fd)
            destination_parent_stat = os.fstat(destination_parent_fd)
            anchor_stat = None
            if created_parents and created_parents[0].parent_fd is not None:
                anchor_stat = os.fstat(created_parents[0].parent_fd)
        except OSError as exc:
            primary = error(
                "storage_failure",
                "cannot inspect restore directories",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            )
            raise _cleanup_and_attach(primary, created_parents, staging_fd) from exc
        if payload_parent_stat.st_dev != destination_parent_stat.st_dev or (
            anchor_stat is not None and anchor_stat.st_dev != payload_parent_stat.st_dev
        ):
            primary = error(
                "cross_device",
                "restore destination and trash are on different filesystems",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
            )
            raise _cleanup_and_attach(primary, created_parents, staging_fd)

        try:
            atomic_move(
                payload,
                destination_path,
                source_parent_fd=payload_parent_fd,
                destination_parent_fd=destination_parent_fd,
                expected_source_stat=payload_stat,
                expected_source_kind=entry.kind,
            )
        except SafeDeleteError as exc:
            raise _cleanup_and_attach(exc, created_parents, staging_fd)

        if created_parents:
            top = created_parents[0]
            if staging_fd is None or top.parent_fd is None or top.staged_name is None:
                primary = error(
                    "storage_failure",
                    "restore parent staging descriptors are unavailable",
                    entry_id=entry.entry_id,
                    path=str(top.path),
                )
                raise _rollback_restore(
                    destination=destination,
                    payload=str(payload),
                    created_parents=created_parents,
                    append_error=primary,
                    destination_parent_fd=destination_parent_fd,
                    payload_parent_fd=payload_parent_fd,
                    payload_stat=payload_stat,
                    kind=entry.kind,
                    staging_fd=staging_fd,
                )
            try:
                _before_publish_hook(top.parent_fd, top.name)
                rename_without_replace(
                    staging_fd,
                    top.staged_name,
                    top.parent_fd,
                    top.name,
                )
            except SafeDeleteError as exc:
                raise _rollback_restore(
                    destination=destination,
                    payload=str(payload),
                    created_parents=created_parents,
                    append_error=exc,
                    destination_parent_fd=destination_parent_fd,
                    payload_parent_fd=payload_parent_fd,
                    payload_stat=payload_stat,
                    kind=entry.kind,
                    staging_fd=staging_fd,
                ) from exc
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    primary = error(
                        "storage_failure",
                        "restore destination parent appeared while it was "
                        "being created; refusing to adopt it",
                        entry_id=entry.entry_id,
                        path=str(top.path),
                    )
                elif is_exdev(exc):
                    primary = error(
                        "cross_device",
                        "restore destination and trash are on different filesystems",
                        entry_id=entry.entry_id,
                        restore_path=destination,
                        trashed_path=str(payload),
                    )
                else:
                    primary = error(
                        "storage_failure",
                        f"cannot publish restore parent: {top.path}",
                        entry_id=entry.entry_id,
                        path=str(top.path),
                        errno=exc.errno,
                    )
                raise _rollback_restore(
                    destination=destination,
                    payload=str(payload),
                    created_parents=created_parents,
                    append_error=primary,
                    destination_parent_fd=destination_parent_fd,
                    payload_parent_fd=payload_parent_fd,
                    payload_stat=payload_stat,
                    kind=entry.kind,
                    staging_fd=staging_fd,
                ) from exc
            for created_parent in created_parents:
                created_parent.published = True
            top.staged_name = None

        metadata = metadata_for_record(entry.creation)
        record = build_restore_record(
            entry_id=entry.entry_id,
            original_path=entry.original_path,
            trashed_path=str(payload),
            kind=entry.kind,
            restore_path=destination,
            metadata=metadata,
        )
        try:
            append_event(layout, record)
        except SafeDeleteError as append_error:
            raise _rollback_restore(
                destination=destination,
                payload=str(payload),
                created_parents=created_parents,
                append_error=append_error,
                destination_parent_fd=destination_parent_fd,
                payload_parent_fd=payload_parent_fd,
                payload_stat=payload_stat,
                kind=entry.kind,
                staging_fd=staging_fd,
            )

        result = {
            "entry_id": entry.entry_id,
            "state": "restored",
            "original_path": entry.original_path,
            "restore_path": destination,
            "trashed_path": str(payload),
            "kind": entry.kind,
        }
        result.update(metadata.projection_fields())
        return result
    finally:
        if destination_parent_fd is not None:
            os.close(destination_parent_fd)
        if payload_parent_fd is not None:
            os.close(payload_parent_fd)
        if staging_fd is not None:
            os.close(staging_fd)
        _close_created_parent_descriptors(created_parents)
