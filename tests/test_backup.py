"""Tests for the backup engine (omarchy_restore.backup)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from omarchy_restore.backup import (
    create_backup,
    default_output_name,
    scan_source,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _populate(source: Path, structure: dict[str, bytes | str]) -> None:
    """Create a directory tree from a dict of relative-path → content.

    Content is bytes for a regular file, or a str starting with ``->`` to
    indicate a symlink target.
    """
    for rel, content in structure.items():
        full = source / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str) and content.startswith("->"):
            target = content[2:]
            full.symlink_to(target)
        else:
            data = content if isinstance(content, bytes) else content.encode()
            full.write_bytes(data)


# ── scan_source ────────────────────────────────────────────────────────────


class TestScanSource:
    def test_basic_scan_counts(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"hello",
            "Documents/todo.md": b"- buy milk\n",
            ".bashrc": b'alias ll="ls -la"\n',
        })
        stats = scan_source(src)
        assert stats.total_files == 3
        assert stats.included_files == 3
        assert stats.excluded == 0
        assert stats.total_bytes > 0

    def test_excludes_app_state(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"keep",
            ".cache/thumbnails/big.jpg": b"\x00" * 100,
            ".local/state/something.db": b"state",
        })
        stats = scan_source(src)
        # .cache/ is pruned from os.walk, so files under it are never visited.
        # .local/state/ is entered; something.db is categorized APP_STATE → excluded.
        assert stats.total_files == 2
        assert stats.included_files == 1
        assert stats.excluded == 1

    def test_excludes_build_artifacts(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "project/main.py": b"print('hello')\n",
            "project/__pycache__/main.cpython-311.pyc": b"\x00" * 50,
            ".venv/bin/python": b"fake",
            "node_modules/foo/index.js": b"fake",
        })
        stats = scan_source(src)
        # __pycache__/, .venv/, node_modules/ are pruned; only project/main.py visited
        assert stats.total_files == 1
        assert stats.included_files == 1
        assert stats.excluded == 0

    def test_excludes_nested_archives(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"keep",
            "backups/old-backup.tar.xz": b"\x00" * 50,
            "backups/backup.tar.gz": b"\x00" * 50,
        })
        stats = scan_source(src)
        assert stats.total_files == 3
        assert stats.included_files == 1
        assert stats.excluded == 2

    def test_excludes_git(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "project/main.py": b"print('hello')\n",
            "project/.git/HEAD": b"ref: refs/heads/main\n",
            "project/.git/objects/ab/abcdef": b"\x00" * 20,
        })
        stats = scan_source(src)
        # .git/ is pruned from os.walk; only project/main.py is visited
        assert stats.total_files == 1
        assert stats.included_files == 1

    def test_symlinks_counted(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/real.txt": b"content",
            "Documents/link.txt": "->real.txt",
        })
        stats = scan_source(src)
        assert stats.total_files == 2
        assert stats.included_files == 2
        assert stats.total_symlinks == 1

    def test_per_category_breakdown(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            ".config/hypr/hyprland.conf": b"monitor=,preferred\n",
            ".bashrc": b'alias ll="ls"\n',
            ".ssh/id_ed25519": b"PRIVATE_KEY\n",
        })
        stats = scan_source(src)
        assert "S" in stats.per_category  # system-config
        assert "H" in stats.per_category  # shell
        assert "K" in stats.per_category  # secrets

    def test_rejects_non_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_bytes(b"x")
        with pytest.raises(NotADirectoryError):
            scan_source(f)


# ── create_backup ──────────────────────────────────────────────────────────


class TestCreateBackup:
    def test_creates_valid_tarxz(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"hello world",
            ".bashrc": b'alias ll="ls"\n',
        })
        out = tmp_path / "backup.tar.xz"
        result = create_backup(src, out)
        assert result.path == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_contents_match(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"hello world",
            ".bashrc": b'alias ll="ls"\n',
        })
        out = tmp_path / "backup.tar.xz"
        create_backup(src, out)

        # Verify contents
        import tarfile
        with tarfile.open(out, "r:xz") as tf:
            names = sorted(m.name for m in tf)
            assert "Documents/notes.txt" in names
            assert ".bashrc" in names
            member = tf.getmember("Documents/notes.txt")
            assert member.size == 11

    def test_skips_excluded_in_archive(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/keep.txt": b"keep",
            ".cache/bad.txt": b"bad",
        })
        out = tmp_path / "backup.tar.xz"
        create_backup(src, out)
        import tarfile
        with tarfile.open(out, "r:xz") as tf:
            names = [m.name for m in tf]
            assert "Documents/keep.txt" in names
            assert ".cache/bad.txt" not in names

    def test_preserves_symlinks(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "target.txt": b"real",
            "link.txt": "->target.txt",
        })
        out = tmp_path / "backup.tar.xz"
        create_backup(src, out)
        import tarfile
        with tarfile.open(out, "r:xz") as tf:
            link = tf.getmember("link.txt")
            assert link.issym()
            assert link.linkname == "target.txt"

    def test_events_emitted(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "a.txt": b"alpha",
            "b.txt": b"beta",
        })
        out = tmp_path / "backup.tar.xz"
        events: list[str] = []
        create_backup(src, out, on_event=lambda e: events.append(e.kind))
        assert "archived" in events
        assert events[-1] == "done"

    def test_cancel_stops_backup(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "a.txt": b"alpha",
            "b.txt": b"beta",
            "c.txt": b"gamma",
        })
        out = tmp_path / "backup.tar.xz"
        cancel_event = threading.Event()
        cancel_event.set()
        events: list[str] = []
        result = create_backup(
            src,
            out,
            on_event=lambda e: events.append(e.kind),
            cancel_event=cancel_event,
        )
        assert len(result.errors) == 0
        # No output file should exist on cancel
        assert not out.exists()

    def test_stats_match_scan(self, tmp_path: Path) -> None:
        src = tmp_path / "home"
        _populate(src, {
            "Documents/notes.txt": b"hello",
            ".cache/foo": b"bar",
        })
        scan = scan_source(src)
        out = tmp_path / "backup.tar.xz"
        result = create_backup(src, out)
        assert result.stats.included_files == scan.included_files
        assert result.stats.excluded == scan.excluded


# ── default_output_name ────────────────────────────────────────────────────


class TestDefaultOutputName:
    def test_returns_non_empty_string(self) -> None:
        name = default_output_name()
        assert name.startswith("omarchy-backup-")
        assert name.endswith(".tar.xz")
        assert len(name) > len("omarchy-backup-.tar.xz")
