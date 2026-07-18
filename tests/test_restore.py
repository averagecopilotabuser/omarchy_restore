"""Restore worker tests."""

from __future__ import annotations

import io
import os
import tarfile
import threading
import time
from pathlib import Path

from omarchy_restore.diff import DiffRow, build_diff
from omarchy_restore.restore import restore_rows


def _build_tarball(path: Path, members: list[tuple[str, dict]]) -> Path:
    tar = path / "fixture.tar.xz"
    with tarfile.open(tar, "w:xz") as tf:
        for name, kw in members:
            data = kw.pop("data", b"")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = kw.pop("mode", 0o644)
            info.mtime = kw.pop("mtime", int(time.time()))
            info.type = kw.pop("type", tarfile.REGTYPE)
            if "linkname" in kw:
                info.linkname = kw.pop("linkname")
            for k, v in kw.items():
                setattr(info, k, v)
            tf.addfile(
                info,
                fileobj=io.BytesIO(data) if data else None,
            )
    return tar


def _rows_from(archive: Path, target: Path) -> list[DiffRow]:
    result = build_diff(archive, target)
    assert result.error is None
    return result.rows


class TestRestoreRegular:
    def test_writes_file_and_content_matches(self, tmp_path: Path) -> None:
        data = b"hello world" * 5000
        archive = _build_tarball(
            tmp_path, [("Documents/a.txt", {"data": data})]
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        res = restore_rows(archive, target, rows)
        assert res.stats.written == 1
        assert res.stats.errors == 0
        assert (target / "Documents" / "a.txt").read_bytes() == data

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path, [("a.txt", {"data": b"new content"})]
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "a.txt").write_bytes(b"old")
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows)
        assert (target / "a.txt").read_bytes() == b"new content"

    def test_strips_setuid_by_default(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("bin/run", {"data": b"#!/bin/sh\n", "mode": 0o4755})],
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows, keep_capabilities=False)
        mode = (target / "bin" / "run").stat().st_mode
        assert not (mode & 0o4000)  # setuid stripped

    def test_keeps_setuid_when_asked(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("bin/run", {"data": b"#!/bin/sh\n", "mode": 0o4755})],
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows, keep_capabilities=True)
        mode = (target / "bin" / "run").stat().st_mode
        assert mode & 0o4000


class TestRestoreSymlinks:
    def test_symlink_written(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("target.txt", {"data": b"data"}),
                (
                    "link.txt",
                    {"type": tarfile.SYMTYPE, "linkname": "target.txt"},
                ),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "target.txt").write_bytes(b"data")  # pre-existing for diff
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows)
        assert (target / "link.txt").is_symlink()
        assert os.readlink(target / "link.txt") == "target.txt"


class TestRestoreSkips:
    def test_fifo_skipped_not_error(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("myfifo", {"type": tarfile.FIFOTYPE, "mode": 0o644})],
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        res = restore_rows(archive, target, rows)
        assert res.stats.skipped == 1
        assert res.stats.errors == 0

    def test_reject_rows_are_not_written(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("/etc/shadow", {"data": b"evil"}),
                ("Documents/ok.txt", {"data": b"fine"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows)
        # The reject row is excluded because include=False.
        assert not (target / "etc" / "shadow").exists()
        assert (target / "Documents" / "ok.txt").read_bytes() == b"fine"


class TestRestoreEvents:
    def test_on_event_called(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path, [("a.txt", {"data": b"x"})]
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        events: list[str] = []
        restore_rows(
            archive, target, rows, on_event=lambda e: events.append(e.kind)
        )
        assert "written" in events
        assert events[-1] == "done"


class TestRestoreInterruptSafety:
    def test_no_partial_file_left_on_disk(self, tmp_path: Path) -> None:
        # Atomic replace: after a successful restore the content is exactly
        # the archive content (no half-written file at the destination).
        data = bytes((i % 251) for i in range(2_000_000))
        archive = _build_tarball(tmp_path, [("big.bin", {"data": data})])
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        restore_rows(archive, target, rows)
        assert (target / "big.bin").read_bytes() == data

    def test_cancel_event_stops_restore(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("a.txt", {"data": b"alpha"}),
                ("b.txt", {"data": b"beta"}),
                ("c.txt", {"data": b"gamma"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        rows = _rows_from(archive, target)
        cancel_event = threading.Event()
        cancel_event.set()
        events: list[tuple[str, str | None]] = []
        res = restore_rows(
            archive, target, rows,
            on_event=lambda e: events.append((e.kind, e.detail)),
            cancel_event=cancel_event,
        )
        assert res.stats.written == 0
        assert res.stats.errors == 0
        assert events[-1] == ("done", "cancelled")
