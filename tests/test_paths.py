"""Tests for the path-safety core. These are the most important tests in the
project — they lock down the invariants every other component relies on."""

from __future__ import annotations

import tarfile
import time
from pathlib import Path

import pytest

from omarchy_restore.paths import (
    PathSafetyError,
    SafetyVerdict,
    check_member,
    is_safe_target,
    resolve_target,
    safe_join,
)

# --- Targets ----------------------------------------------------------------


class TestResolveTarget:
    def test_accepts_normal_home(self, tmp_path: Path) -> None:
        p = resolve_target(tmp_path)
        assert p == tmp_path.resolve()

    def test_accepts_tilde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/home/test")
        assert str(resolve_target("~")) == "/home/test"

    @pytest.mark.parametrize("forbidden", ["/", "/etc", "/usr", "/var"])
    def test_rejects_forbidden_top_level(
        self, forbidden: str
    ) -> None:
        if forbidden == "/":
            with pytest.raises(PathSafetyError, match="system path"):
                resolve_target(forbidden)
            return
        with pytest.raises(PathSafetyError, match="system path"):
            resolve_target(forbidden)

    def test_rejects_ancestor_of_forbidden(self) -> None:
        # /etc is forbidden; /etc/passwd is also forbidden (descendant).
        with pytest.raises(PathSafetyError, match="system path"):
            resolve_target("/etc")


# --- safe_join --------------------------------------------------------------


class TestSafeJoin:
    def test_simple_join(self, tmp_path: Path) -> None:
        out = safe_join(tmp_path, "Documents/report.pdf")
        assert out == (tmp_path / "Documents" / "report.pdf").resolve(strict=False)

    def test_rejects_absolute(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError, match="absolute"):
            safe_join(tmp_path, "/etc/passwd")

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError, match=r"\.\."):
            safe_join(tmp_path, "../escape")

    def test_rejects_deep_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError, match=r"\.\."):
            safe_join(tmp_path, "a/b/../../../etc/passwd")

    def test_rejects_empty(self, tmp_path: Path) -> None:
        with pytest.raises(PathSafetyError, match="empty"):
            safe_join(tmp_path, "")

    def test_does_not_resolve_existing_symlinks(self, tmp_path: Path) -> None:
        # safe_join does not consult the filesystem; the symlink is checked
        # lexically only.
        link_name = "Documents/innocent"
        out = safe_join(tmp_path, link_name)
        assert out == (tmp_path / "Documents" / "innocent").resolve(strict=False)


# --- check_member -----------------------------------------------------------


class TestCheckMember:
    def test_safe_regular_file(self, tmp_path: Path) -> None:
        v = check_member(
            "Documents/report.pdf",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o644,
            target=tmp_path,
        )
        assert v.ok

    def test_rejects_absolute_member(self, tmp_path: Path) -> None:
        v = check_member(
            "/etc/passwd",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o644,
            target=tmp_path,
        )
        assert not v.ok
        assert "absolute" in (v.reason or "")

    def test_rejects_traversal_member(self, tmp_path: Path) -> None:
        v = check_member(
            "../../etc/shadow",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o600,
            target=tmp_path,
        )
        assert not v.ok
        assert ".." in (v.reason or "")

    def test_rejects_absolute_symlink_to_outside(self, tmp_path: Path) -> None:
        v = check_member(
            "Documents/leak",
            is_symlink=True,
            link_target="/etc/shadow",
            is_hardlink=False,
            mode=0o777,
            target=tmp_path,
        )
        assert not v.ok
        assert "outside target" in (v.reason or "")

    def test_allows_absolute_symlink_inside(self, tmp_path: Path) -> None:
        v = check_member(
            "Documents/link",
            is_symlink=True,
            link_target=str((tmp_path / "Documents" / "real").resolve()),
            is_hardlink=False,
            mode=0o777,
            target=tmp_path,
        )
        assert v.ok

    def test_rejects_relative_symlink_traversal(self, tmp_path: Path) -> None:
        v = check_member(
            "Documents/leak",
            is_symlink=True,
            link_target="../../../etc/shadow",
            is_hardlink=False,
            mode=0o777,
            target=tmp_path,
        )
        assert not v.ok
        assert ".." in (v.reason or "")

    def test_rejects_hardlink_outside(self, tmp_path: Path) -> None:
        v = check_member(
            "Documents/leak",
            is_symlink=False,
            link_target="../../etc/passwd",
            is_hardlink=True,
            mode=0o644,
            target=tmp_path,
        )
        assert not v.ok
        assert "hardlink" in (v.reason or "").lower()

    def test_flags_special_mode_but_allows(self, tmp_path: Path) -> None:
        v = check_member(
            "bin/sudo-wrapper",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o4755,
            target=tmp_path,
        )
        assert v.ok
        assert "special mode" in (v.reason or "").lower()

    def test_dotfile_in_subdir(self, tmp_path: Path) -> None:
        v = check_member(
            ".config/hypr/hyprland.conf",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o644,
            target=tmp_path,
        )
        assert v.ok

    def test_root_member(self, tmp_path: Path) -> None:
        # An archive whose top-level entry is just "." is common.
        v = check_member(
            ".",
            is_symlink=False,
            link_target=None,
            is_hardlink=False,
            mode=0o755,
            target=tmp_path,
        )
        assert v.ok


# --- End-to-end with a real tarball -----------------------------------------


def _build_tarball(path: Path, members: list[tuple[str, dict]]) -> Path:
    """Build a tar.xz with the given (name, kwargs) members."""
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
            tf.addfile(info, fileobj=__import__("io").BytesIO(data) if data else None)
    return tar


class TestEndToEndTarball:
    def test_crafted_evil_archive_rejects_every_unsafe_member(
        self, tmp_path: Path
    ) -> None:
        archive = _build_tarball(
            tmp_path,
            [
                # Legitimate entries:
                ("home/user/Documents/report.pdf", {"data": b"ok"}),
                (
                    "home/user/rel-sym-ok",
                    {
                        "data": b"",
                        "type": tarfile.SYMTYPE,
                        "linkname": "Documents/report.pdf",
                    },
                ),
                # Evils:
                ("home/user/../../etc/passwd", {"data": b"evil"}),
                ("/etc/shadow", {"data": b"evil"}),
                (
                    "home/user/leak-sym-abs",
                    {
                        "data": b"",
                        "type": tarfile.SYMTYPE,
                        "linkname": "/etc/shadow",
                    },
                ),
                (
                    "home/user/leak-sym-rel",
                    {
                        "data": b"",
                        "type": tarfile.SYMTYPE,
                        "linkname": "../../etc/shadow",
                    },
                ),
                (
                    "home/user/leak-hardlink",
                    {
                        "data": b"",
                        "type": tarfile.LNKTYPE,
                        "linkname": "../../etc/passwd",
                    },
                ),
                (
                    "home/user/leak-sym-to-proc",
                    {
                        "data": b"",
                        "type": tarfile.SYMTYPE,
                        "linkname": "/proc/self/mem",
                    },
                ),
            ],
        )
        target = tmp_path / "home" / "user"
        target.mkdir(parents=True)

        from omarchy_restore.archive import iter_members  # local import: tests

        verdicts: list[tuple[str, SafetyVerdict]] = []
        for member in iter_members(archive):
            v = check_member(
                member.name,
                is_symlink=member.issym(),
                link_target=(
                    member.linkname if (member.issym() or member.islnk()) else None
                ),
                is_hardlink=member.islnk(),
                mode=member.mode,
                target=target,
            )
            verdicts.append((member.name, v))

        by_name = {n: v for n, v in verdicts}

        # The two legitimate entries pass.
        assert by_name["home/user/Documents/report.pdf"].ok
        assert by_name["home/user/rel-sym-ok"].ok

        # Everything else is rejected.
        assert not by_name["home/user/../../etc/passwd"].ok
        assert not by_name["/etc/shadow"].ok
        assert not by_name["home/user/leak-sym-abs"].ok
        assert not by_name["home/user/leak-sym-rel"].ok
        assert not by_name["home/user/leak-hardlink"].ok
        assert not by_name["home/user/leak-sym-to-proc"].ok


# --- is_safe_target ---------------------------------------------------------


class TestIsSafeTarget:
    def test_home_is_safe(self, tmp_path: Path) -> None:
        assert is_safe_target(tmp_path)

    @pytest.mark.parametrize("forbidden", ["/", "/etc", "/usr"])
    def test_forbidden_is_unsafe(self, forbidden: str) -> None:
        assert not is_safe_target(forbidden)
