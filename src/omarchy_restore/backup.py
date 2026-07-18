"""Create a tar.xz backup archive from a source directory.

Design mirrors restore.py: streaming, temp-file safety, event callbacks.
Exclusions mirror the restore tool's defaults (APP_STATE + build artifacts).
"""

from __future__ import annotations

import os
import stat
import tarfile
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from omarchy_restore.omarchy import Category, categorize

# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------

_EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".egg-info",
    ".tar.xz",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".zip",
)

_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "bower_components",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".pyright_cache",
    ".eggs",
    ".svn",
    ".hg",
    ".cache",
})


def _should_exclude(name: str, rel_path: str) -> bool:
    """Return True if this path should be excluded from backup."""
    if name.lower().endswith(_EXCLUDED_SUFFIXES):
        return True
    parts = rel_path.split("/")
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return True
    return categorize(rel_path) is Category.APP_STATE


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class BackupScan:
    total_files: int = 0
    total_dirs: int = 0
    total_symlinks: int = 0
    total_bytes: int = 0
    included_files: int = 0
    included_dirs: int = 0
    included_symlinks: int = 0
    included_bytes: int = 0
    excluded: int = 0
    per_category: dict[str, int] = field(default_factory=dict)


@dataclass
class BackupEvent:
    kind: str  # "archived" | "skipped" | "error" | "done"
    path: str = ""
    detail: str | None = None
    bytes_processed: int = 0


@dataclass
class BackupResult:
    path: Path
    stats: BackupScan = field(default_factory=BackupScan)
    errors: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_source(source: Path) -> BackupScan:
    """Walk *source* and produce a BackupScan without creating an archive."""
    stats = BackupScan()
    source = source.resolve()
    if not source.is_dir():
        raise NotADirectoryError(f"not a directory: {source}")

    for dirpath_str, dirnames, filenames in os.walk(source, followlinks=False):
        dirpath = Path(dirpath_str)
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

        for name in filenames:
            full = dirpath / name
            rel = full.relative_to(source)
            try:
                st = full.lstat()
            except OSError:
                continue

            stats.total_files += 1
            stats.total_bytes += st.st_size

            if stat.S_ISLNK(st.st_mode):
                stats.total_symlinks += 1

            if _should_exclude(name, str(rel)):
                stats.excluded += 1
            else:
                stats.included_files += 1
                stats.included_bytes += st.st_size
                cat = categorize(str(rel))
                stats.per_category[cat.value] = (
                    stats.per_category.get(cat.value, 0) + 1
                )

    return stats


def create_backup(
    source: Path,
    output: Path,
    *,
    on_event: Callable[[BackupEvent], object] | None = None,
    cancel_event: threading.Event | None = None,
) -> BackupResult:
    """Create a tar.xz archive from *source* and write it to *output*.

    Writes to a temp file in the same directory, fsyncs, then atomically
    renames into place so a crash or cancel never leaves a partial file.
    """
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    tmp_path_str = tempfile.mktemp(
        dir=str(output.parent),
        prefix=".omr-backup-",
        suffix=".tar.xz",
    )
    tmp_path = Path(tmp_path_str)
    result = BackupResult(path=output)
    stats = BackupScan()

    try:
        with tarfile.open(tmp_path, mode="w:xz") as tf:
            for dirpath_str, dirnames, filenames in os.walk(
                source, followlinks=False
            ):
                dirpath = Path(dirpath_str)
                dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

                if cancel_event is not None and cancel_event.is_set():
                    if on_event:
                        on_event(BackupEvent("done", "", "cancelled"))
                    return BackupResult(path=output, stats=stats)

                # Add directory entry (skip source root)
                if dirpath != source:
                    _add_directory_entry(tf, dirpath, source, stats)

                for name in filenames:
                    full = dirpath / name
                    rel_str = str(full.relative_to(source))

                    if cancel_event is not None and cancel_event.is_set():
                        if on_event:
                            on_event(BackupEvent("done", "", "cancelled"))
                        return BackupResult(path=output, stats=stats)

                    try:
                        st = full.lstat()
                    except OSError as exc:
                        result.errors.append((rel_str, str(exc)))
                        if on_event:
                            on_event(
                                BackupEvent("error", rel_str, str(exc))
                            )
                        continue

                    stats.total_files += 1
                    stats.total_bytes += st.st_size

                    if stat.S_ISLNK(st.st_mode):
                        stats.total_symlinks += 1

                    if _should_exclude(name, rel_str):
                        stats.excluded += 1
                        if on_event:
                            on_event(
                                BackupEvent("skipped", rel_str, "excluded")
                            )
                        continue

                    stats.included_files += 1
                    stats.included_bytes += st.st_size
                    cat = categorize(rel_str)
                    stats.per_category[cat.value] = (
                        stats.per_category.get(cat.value, 0) + 1
                    )

                    try:
                        _add_file_entry(tf, full, rel_str, st, stats)
                        if on_event:
                            on_event(
                                BackupEvent(
                                    "archived",
                                    rel_str,
                                    None,
                                    st.st_size,
                                )
                            )
                    except Exception as exc:
                        result.errors.append((rel_str, str(exc)))
                        if on_event:
                            on_event(
                                BackupEvent("error", rel_str, str(exc))
                            )

        # tarfile closed — archive is complete on disk
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

    os.replace(tmp_path, output)
    result.stats = stats

    if on_event:
        on_event(
            BackupEvent(
                "done",
                str(output),
                f"{stats.included_files} files, {stats.included_bytes} bytes",
            )
        )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _add_directory_entry(tf, dirpath: Path, source: Path, stats: BackupScan) -> None:
    """Add a directory entry to the tar archive."""
    try:
        info = tf.gettarinfo(name=str(dirpath), arcname=str(dirpath.relative_to(source)))
        if info is not None and info.isdir():
            tf.addfile(info)
            stats.total_dirs += 1
            stats.included_dirs += 1
    except OSError:
        pass


def _add_file_entry(tf, full: Path, rel_str: str, st, stats: BackupScan) -> None:
    """Add a file or symlink entry to the tar archive."""
    if stat.S_ISLNK(st.st_mode):
        info = tarfile.TarInfo(name=rel_str)
        info.type = tarfile.SYMTYPE
        info.linkname = os.readlink(full)
        info.mode = st.st_mode
        info.mtime = int(st.st_mtime)
        info.uid = st.st_uid
        info.gid = st.st_gid
        tf.addfile(info)
        stats.total_symlinks += 1
        stats.included_symlinks += 1
    elif stat.S_ISREG(st.st_mode):
        info = tarfile.TarInfo(name=rel_str)
        info.size = st.st_size
        info.mode = st.st_mode
        info.mtime = int(st.st_mtime)
        info.uid = st.st_uid
        info.gid = st.st_gid
        with full.open("rb") as fh:
            tf.addfile(info, fh)
    else:
        tf.addfile(tf.gettarinfo(name=str(full), arcname=rel_str))


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def default_output_name() -> str:
    """Return a timestamped default filename like
    ``omarchy-backup-20260718-143022.tar.xz``."""
    return f"omarchy-backup-{datetime.now():%Y%m%d-%H%M%S}.tar.xz"
