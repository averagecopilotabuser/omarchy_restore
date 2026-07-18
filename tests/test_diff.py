"""Diff engine tests."""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

from omarchy_restore.diff import (
    DiffRow,
    DiffStatus,
    build_diff,
    compare_member_content,
)
from omarchy_restore.omarchy import Category


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


class TestBuildDiff:
    def test_new_vs_overwrite_vs_same(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("Documents/new.txt", {"data": b"new"}),
                ("Documents/overwrite.txt", {"data": b"new content here"}),
                ("Documents/same.txt", {"data": b"identical"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "Documents").mkdir(parents=True)
        (target / "Documents" / "overwrite.txt").write_bytes(b"old content here")
        (target / "Documents" / "same.txt").write_bytes(b"identical")

        result = build_diff(archive, target)
        assert result.error is None
        by_name = {r.name: r for r in result.rows}

        assert by_name["Documents/new.txt"].status is DiffStatus.NEW
        assert by_name["Documents/overwrite.txt"].status is DiffStatus.OVERWRITE
        assert by_name["Documents/same.txt"].status is DiffStatus.SAME

    def test_overwrite_by_size_only(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("a.txt", {"data": b"x" * 100})],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "a.txt").write_bytes(b"y" * 100)  # same size, diff content
        result = build_diff(archive, target)
        row = result.rows[0]
        assert row.status is DiffStatus.OVERWRITE  # differing sha256

    def test_overwrite_dir(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("docs/", {"type": tarfile.DIRTYPE, "mode": 0o755}),
                ("docs/inner.txt", {"data": b"hi"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "docs").mkdir()
        (target / "docs" / "existing.txt").write_bytes(b"already there")
        result = build_diff(archive, target)
        dir_row = next(r for r in result.rows if r.name == "docs")
        assert dir_row.status is DiffStatus.OVERWRITE_DIR

    def test_symlink_new_and_overwrite(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                (
                    "link-new",
                    {"type": tarfile.SYMTYPE, "linkname": "Documents/new.txt"},
                ),
                (
                    "link-existing",
                    {"type": tarfile.SYMTYPE, "linkname": "Documents/same.txt"},
                ),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "Documents").mkdir()
        (target / "Documents" / "same.txt").write_bytes(b"x")
        (target / "link-existing").symlink_to("Documents/same.txt")
        result = build_diff(archive, target)
        by_name = {r.name: r for r in result.rows}
        assert by_name["link-new"].status is DiffStatus.NEW
        assert by_name["link-existing"].status is DiffStatus.OVERWRITE

    def test_reject_unsafe_member(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("/etc/shadow", {"data": b"evil"})],
        )
        target = tmp_path / "home"
        target.mkdir()
        result = build_diff(archive, target)
        row = result.rows[0]
        assert row.status is DiffStatus.REJECT
        assert not row.include
        assert row.reason is not None

    def test_categories_assigned(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                (".config/hypr/hyprland.conf", {"data": b"x"}),
                (".config/omarchy/themes/foo/theme.json", {"data": b"{}"}),
                (".cache/something", {"data": b"x"}),
                ("Documents/report.pdf", {"data": b"x"}),
                (".ssh/id_ed25519", {"data": b"x"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / ".config" / "hypr").mkdir(parents=True)
        (target / ".config" / "omarchy" / "themes" / "foo").mkdir(parents=True)
        (target / ".cache").mkdir()
        (target / "Documents").mkdir()
        (target / ".ssh").mkdir()
        result = build_diff(archive, target)
        by_name = {r.name: r for r in result.rows}
        assert by_name[".config/hypr/hyprland.conf"].category is Category.SYSTEM_CONFIG
        assert by_name[".config/omarchy/themes/foo/theme.json"].category is Category.OMARCHY_THEME
        assert by_name[".cache/something"].category is Category.APP_STATE
        assert by_name["Documents/report.pdf"].category is Category.USER_DATA
        assert by_name[".ssh/id_ed25519"].category is Category.SECRETS
        # app-state excluded by default
        assert not by_name[".cache/something"].include

    def test_default_include_policy(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("Documents/a.txt", {"data": b"x"}),
                (".cache/b", {"data": b"x"}),
                (".ssh/key", {"data": b"x"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "Documents").mkdir()
        (target / ".cache").mkdir()
        (target / ".ssh").mkdir()
        result = build_diff(archive, target)
        by_name = {r.name: r for r in result.rows}
        assert by_name["Documents/a.txt"].include
        assert by_name[".ssh/key"].include
        assert not by_name[".cache/b"].include


class TestDiffResult:
    def test_summary_counts(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                ("Documents/new.txt", {"data": b"new"}),
                ("Documents/over.txt", {"data": b"brand new content"}),
                (".cache/c", {"data": b"x"}),
            ],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "Documents").mkdir()
        (target / "Documents" / "over.txt").write_bytes(b"old content here")
        (target / ".cache").mkdir()
        result = build_diff(archive, target)
        s = result.summary()
        # new.txt + .cache/c are both NEW by status (cache excluded later).
        assert s["NEW"] == 2
        assert s["OVERWRITE"] == 1
        assert s["total"] == 3
        # included = new.txt + overwrite (cache excluded)
        assert len(result.included()) == 2

    def test_modifying_include_toggles_included(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("Documents/a.txt", {"data": b"x"})],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "Documents").mkdir()
        result = build_diff(archive, target)
        row = result.rows[0]
        row.include = False
        assert len(result.included()) == 0


class TestSelectAllSkipsReject:
    def test_select_all_does_not_toggle_rejected(self, tmp_path: Path) -> None:
        """Simulate action_select_all logic on diff rows."""
        reject = DiffRow(
            name="/etc/shadow",
            status=DiffStatus.REJECT,
            category=Category.SECRETS,
            archive_size=100,
            disk_size=None,
            delta_bytes=100,
            include=False,
            reason="unsafe path",
        )
        normal = DiffRow(
            name="Documents/a.txt",
            status=DiffStatus.NEW,
            category=Category.USER_DATA,
            archive_size=10,
            disk_size=None,
            delta_bytes=10,
            include=False,
        )
        rows = [reject, normal]
        for r in rows:
            if r.status is not DiffStatus.REJECT:
                r.include = True
        assert not reject.include
        assert normal.include


class TestFormatBytes:
    def test_format_bytes_outputs(self) -> None:
        from omarchy_restore.tui.screens import _format_bytes
        assert _format_bytes(0) == "0B"
        assert _format_bytes(500) == "500B"
        assert _format_bytes(1023) == "1023B"
        assert _format_bytes(1024) == "1.0KB"
        assert _format_bytes(1536) == "1.5KB"
        assert _format_bytes(1_048_576) == "1.0MB"
        assert _format_bytes(1_073_741_824) == "1.0GB"


class TestCompareMemberContent:
    def test_equal(self, tmp_path: Path) -> None:
        data = b"hello world" * 1000
        archive = _build_tarball(
            tmp_path,
            [("f.txt", {"data": data, "mtime": 1000})],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "f.txt").write_bytes(data)
        with tarfile.open(archive, "r:*") as tf:
            member = next(m for m in tf if m.name == "f.txt")
            assert compare_member_content(target / "f.txt", member, tf)

    def test_differs(self, tmp_path: Path) -> None:
        archive = _build_tarball(
            tmp_path,
            [("f.txt", {"data": b"hello world"})],
        )
        target = tmp_path / "home"
        target.mkdir()
        (target / "f.txt").write_bytes(b"different!!")
        with tarfile.open(archive, "r:*") as tf:
            member = next(m for m in tf if m.name == "f.txt")
            assert not compare_member_content(target / "f.txt", member, tf)
