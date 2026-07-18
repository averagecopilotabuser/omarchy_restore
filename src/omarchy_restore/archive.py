"""Streaming iteration over tar.xz members without extraction.

This module wraps Python's ``tarfile`` so the rest of the codebase can
consume an archive one member at a time without ever invoking extract.
"""

from __future__ import annotations

import os
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_archive(archive: str | os.PathLike[str]) -> Iterator[tarfile.TarFile]:
    """Open a tar.xz (auto-detect mode) and yield it for streaming."""
    archive_path = Path(archive)
    if not archive_path.exists():
        raise FileNotFoundError(f"archive not found: {archive_path}")
    if not tarfile.is_tarfile(archive_path):
        raise tarfile.ReadError(f"not a valid tar file: {archive_path}")
    # 'r:*' auto-detects compression; '*' includes xz, gz, bz2, plain.
    with tarfile.open(archive_path, mode="r:*") as tf:
        yield tf


def iter_members(archive: str | os.PathLike[str]) -> Iterator[tarfile.TarInfo]:
    """Yield each member of the archive in order. Does not extract."""
    with open_archive(archive) as tf:
        yield from tf


def archive_summary(archive: str | os.PathLike[str]) -> dict:
    """Return a summary of the archive: counts, sizes, top-level dirs."""
    files = dirs = symlinks = 0
    uncompressed = 0
    top_levels: set[str] = set()
    with open_archive(archive) as tf:
        for m in tf:
            if m.isdir():
                dirs += 1
            elif m.issym() or m.islnk():
                symlinks += 1
            else:
                files += 1
            uncompressed += m.size
            # First path component under the archive.
            parts = m.name.split("/", 1)
            top_levels.add(parts[0])
    return {
        "files": files,
        "dirs": dirs,
        "symlinks": symlinks,
        "total_members": files + dirs + symlinks,
        "uncompressed_bytes": uncompressed,
        "top_level": sorted(top_levels),
    }
