"""P10 DrvFs fallback. These tests simulate 9p; they are not host H4/H5 evidence."""

from __future__ import annotations

import errno
import os
import stat
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from safe_delete.doctor import run_doctor
from safe_delete.errors import FROZEN_ERROR_CODES, SafeDeleteError
from safe_delete.human import render
from safe_delete.move import (
    V9FS_MAGIC,
    V9FS_NOREPLACE_RESIDUAL,
    _filesystem_type,
    atomic_move,
)
import safe_delete.cli as cli
import safe_delete.move as move


_OVERLAYFS_SUPER_MAGIC = 0x794c7630
_TMPFS_MAGIC = 0x01021994


class P10DrvFsFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-p10-")
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.storage = Path(self.temp_dir.name) / "safe-delete"
        self.addCleanup(self.temp_dir.cleanup)

    def _reject_noreplace(self, err: int):
        calls: list[int] = []

        def reject(
            source_parent_fd: int,
            source_name: str,
            destination_parent_fd: int,
            destination_name: str,
            flags: int,
        ) -> None:
            del source_parent_fd, source_name, destination_parent_fd, destination_name
            calls.append(flags)
            raise OSError(err, os.strerror(err))

        return calls, reject

    def test_v9fs_einval_falls_back_to_flags0_rename_for_each_kind(self) -> None:
        directory = self.workspace / "dir"
        directory.mkdir()
        (directory / "child.txt").write_text("child", encoding="utf-8")
        link = self.workspace / "link"
        link.symlink_to("target-text")
        regular = self.workspace / "file.txt"
        regular.write_text("payload", encoding="utf-8")

        for source, kind in (
            (regular, "file"),
            (directory, "directory"),
            (link, "symlink"),
        ):
            with self.subTest(kind=kind):
                destination = self.workspace / f"dest-{kind}"
                before = os.lstat(source)
                calls, reject = self._reject_noreplace(errno.EINVAL)
                renamed: list[dict[str, object]] = []
                real_rename = os.rename

                def flags0_rename(src: str, dst: str, **kwargs: object) -> None:
                    self.assertNotIn("flags", kwargs)
                    renamed.append({"src": src, "dst": dst, **kwargs})
                    real_rename(src, dst, **kwargs)

                with patch.object(move, "_invoke_renameat2", side_effect=reject):
                    with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
                        with patch.object(move.os, "rename", side_effect=flags0_rename):
                            atomic_move(
                                source,
                                destination,
                                expected_source_stat=before,
                                expected_source_kind=kind,
                            )
                self.assertEqual(calls, [move._RENAME_NOREPLACE])
                self.assertEqual(len(renamed), 1)
                self.assertFalse(source.exists() or source.is_symlink())
                after = os.lstat(destination)
                self.assertEqual(after.st_dev, before.st_dev)
                self.assertEqual(after.st_ino, before.st_ino)
                if kind == "file":
                    self.assertEqual(destination.read_text(encoding="utf-8"), "payload")
                elif kind == "directory":
                    self.assertEqual(
                        (destination / "child.txt").read_text(encoding="utf-8"),
                        "child",
                    )
                else:
                    self.assertEqual(os.readlink(destination), "target-text")

    def test_v9fs_enotsup_class_also_uses_flags0_rename(self) -> None:
        self.assertIn(errno.ENOTSUP, move._V9FS_FALLBACK_ERRNOS)
        self.assertIn(errno.EOPNOTSUPP, move._V9FS_FALLBACK_ERRNOS)
        seen: list[int] = []
        for err in (errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP):
            if err in seen:
                continue
            seen.append(err)
            with self.subTest(errno=err):
                source = self.workspace / f"src-{err}"
                destination = self.workspace / f"dst-{err}"
                source.write_text("ok", encoding="utf-8")
                _calls, reject = self._reject_noreplace(err)
                with patch.object(move, "_invoke_renameat2", side_effect=reject):
                    with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
                        atomic_move(source, destination, expected_source_kind="file")
                self.assertEqual(destination.read_text(encoding="utf-8"), "ok")
                self.assertFalse(source.exists())

    def test_occupied_destination_after_v9fs_einval_is_not_renamed(self) -> None:
        cases = (
            ("entry_id_collision", False),
            ("destination_exists", False),
            ("destination_exists", True),
        )
        for code, dangling in cases:
            with self.subTest(code=code, dangling=dangling):
                source = self.workspace / f"src-{code}-{dangling}"
                destination = self.workspace / f"dst-{code}-{dangling}"
                source.write_text("source-bytes", encoding="utf-8")

                def reject_and_occupy(
                    source_parent_fd: int,
                    source_name: str,
                    destination_parent_fd: int,
                    destination_name: str,
                    flags: int,
                ) -> None:
                    del source_parent_fd, source_name
                    self.assertEqual(flags, 1)
                    if dangling:
                        os.symlink(
                            "missing-target",
                            destination_name,
                            dir_fd=destination_parent_fd,
                        )
                    else:
                        fd = os.open(
                            destination_name,
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                            0o600,
                            dir_fd=destination_parent_fd,
                        )
                        os.write(fd, b"occupied")
                        os.close(fd)
                    raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))

                with patch.object(move, "_invoke_renameat2", side_effect=reject_and_occupy):
                    with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
                        with patch.object(move.os, "rename", side_effect=AssertionError("rename")):
                            with self.assertRaises(SafeDeleteError) as raised:
                                atomic_move(
                                    source,
                                    destination,
                                    destination_error_code=code,
                                )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(source.read_text(encoding="utf-8"), "source-bytes")
                if dangling:
                    self.assertTrue(stat.S_ISLNK(os.lstat(destination).st_mode))
                else:
                    self.assertEqual(destination.read_text(encoding="utf-8"), "occupied")

    def test_non_v9fs_einval_stays_storage_failure(self) -> None:
        source = self.workspace / "stay.txt"
        destination = self.workspace / "absent.txt"
        source.write_text("stay", encoding="utf-8")
        calls, reject = self._reject_noreplace(errno.EINVAL)
        with patch.object(move, "_invoke_renameat2", side_effect=reject):
            with patch.object(move, "_filesystem_type", return_value=_OVERLAYFS_SUPER_MAGIC):
                with patch.object(move.os, "rename", side_effect=AssertionError("rename")):
                    with self.assertRaises(SafeDeleteError) as raised:
                        atomic_move(source, destination)
        self.assertEqual(raised.exception.code, "storage_failure")
        self.assertEqual(raised.exception.details["errno"], errno.EINVAL)
        self.assertEqual(calls, [1])
        self.assertEqual(source.read_text(encoding="utf-8"), "stay")
        self.assertFalse(destination.exists())

    def test_non_v9fs_enosys_stays_unavailable_without_rename(self) -> None:
        source = self.workspace / "enosys.txt"
        destination = self.workspace / "enosys-dest.txt"
        source.write_text("stay", encoding="utf-8")
        _calls, reject = self._reject_noreplace(errno.ENOSYS)
        with patch.object(move, "_invoke_renameat2", side_effect=reject):
            with patch.object(move, "_filesystem_type", return_value=_OVERLAYFS_SUPER_MAGIC):
                with patch.object(move.os, "rename", side_effect=AssertionError("rename")):
                    with self.assertRaises(SafeDeleteError) as raised:
                        atomic_move(source, destination)
        self.assertEqual(raised.exception.code, "storage_failure")
        self.assertIn("unavailable", raised.exception.message)
        self.assertNotIn("errno", raised.exception.details)
        self.assertTrue(source.is_file())

    @unittest.skipUnless(
        Path("/dev/shm").is_dir() and os.stat("/dev/shm").st_dev != os.stat("/tmp").st_dev,
        "this host does not provide a distinct /dev/shm filesystem",
    )
    def test_cross_device_does_not_rename_or_copy(self) -> None:
        source_fd, source_name = tempfile.mkstemp(prefix="safe-delete-p10-", dir="/dev/shm")
        os.close(source_fd)
        source = Path(source_name)
        self.addCleanup(source.unlink, missing_ok=True)
        source.write_text("stay", encoding="utf-8")
        destination = self.workspace / "other-device.txt"

        def forbid_renameat2(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("renameat2")

        with patch.object(move, "_invoke_renameat2", side_effect=forbid_renameat2):
            with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
                with patch.object(move.os, "rename", side_effect=AssertionError("rename")):
                    with self.assertRaises(SafeDeleteError) as raised:
                        atomic_move(source, destination)
        self.assertEqual(raised.exception.code, "cross_device")
        self.assertEqual(source.read_text(encoding="utf-8"), "stay")
        self.assertFalse(destination.exists())

    def test_add_uses_v9fs_fallback_and_keeps_inode(self) -> None:
        self.assertEqual(cli.initialize_layout(str(self.storage)).root, self.storage.resolve())
        source = self.workspace / "added.txt"
        source.write_text("added", encoding="utf-8")
        before = os.lstat(source)
        _calls, reject = self._reject_noreplace(errno.EINVAL)
        args = Namespace(
            root=str(self.storage),
            paths=[str(source)],
            dry_run=False,
            reason=None,
            project=None,
            session_id=None,
            agent=None,
            tool=None,
            extensions=None,
        )
        with patch.object(move, "_invoke_renameat2", side_effect=reject):
            with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
                results, errors = cli._handle_add(args)
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["state"], "active")
        self.assertEqual(results[0]["kind"], "file")
        payload = Path(results[0]["trashed_path"])
        moved = os.lstat(payload)
        self.assertEqual(moved.st_dev, before.st_dev)
        self.assertEqual(moved.st_ino, before.st_ino)
        self.assertEqual(payload.read_text(encoding="utf-8"), "added")
        self.assertFalse(source.exists())

    def test_frozen_error_codes_gain_no_drvfs_string(self) -> None:
        lowered = {code.lower() for code in FROZEN_ERROR_CODES}
        self.assertNotIn("drvfs", lowered)
        self.assertNotIn("v9fs", lowered)
        self.assertIn("cross_device", FROZEN_ERROR_CODES)
        self.assertIn("storage_failure", FROZEN_ERROR_CODES)
        self.assertIn("entry_id_collision", FROZEN_ERROR_CODES)
        self.assertIn("destination_exists", FROZEN_ERROR_CODES)
        source = Path(move.__file__).read_text(encoding="utf-8")
        self.assertNotIn("os.link(", source)
        self.assertNotIn("libc.linkat", source)
        self.assertNotIn("shutil", source)
        self.assertNotIn("sendfile", source)

    def test_local_mount_is_not_treated_as_drvfs_evidence(self) -> None:
        mounts = Path("/proc/mounts").read_text(encoding="utf-8") if Path("/proc/mounts").is_file() else ""
        fd = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            magic = _filesystem_type(fd)
        finally:
            os.close(fd)
        self.assertIsNotNone(magic)
        if "\t9p " not in mounts and "drvfs" not in mounts:
            self.assertNotEqual(magic, V9FS_MAGIC)
        if Path("/dev/shm").is_dir():
            shm = os.open("/dev/shm", os.O_RDONLY | os.O_DIRECTORY)
            try:
                shm_magic = _filesystem_type(shm)
            finally:
                os.close(shm)
            self.assertNotEqual(shm_magic, V9FS_MAGIC)
            if shm_magic == _TMPFS_MAGIC:
                self.assertNotEqual(_TMPFS_MAGIC, V9FS_MAGIC)


class P10DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-p10-doctor-")
        self.base = Path(self.temp_dir.name)
        self.storage = self.base / "safe-delete"
        self.environment = {
            "HOME": str(self.base / "home"),
            "XDG_DATA_HOME": str(self.base / "data"),
            "XDG_CONFIG_HOME": str(self.base / "config"),
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)
        cli.initialize_layout(str(self.storage))

    def test_v9fs_root_is_emulated_without_needs_attention(self) -> None:
        with patch.object(move, "_filesystem_type", return_value=V9FS_MAGIC):
            report = run_doctor(str(self.storage))
        self.assertFalse(report["needs_attention"], report["problems"])
        self.assertEqual(report["problems"], [])
        storage = report["storage"]
        self.assertEqual(storage["filesystem"], "v9fs")
        self.assertEqual(storage["noreplace"], "emulated")
        self.assertEqual(storage["noreplace_residual"], V9FS_NOREPLACE_RESIDUAL)
        text = render("doctor", [report], [], root=str(self.storage))
        self.assertIn(V9FS_NOREPLACE_RESIDUAL, text)

    def test_non_v9fs_root_is_native_and_omits_residual_text(self) -> None:
        report = run_doctor(str(self.storage))
        self.assertFalse(report["needs_attention"], report["problems"])
        storage = report["storage"]
        self.assertEqual(storage["noreplace"], "native")
        self.assertIsNone(storage["noreplace_residual"])
        self.assertNotIn("filesystem", storage)
        text = render("doctor", [report], [], root=str(self.storage))
        self.assertNotIn(V9FS_NOREPLACE_RESIDUAL, text)
        self.assertNotIn("RENAME_NOREPLACE", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
