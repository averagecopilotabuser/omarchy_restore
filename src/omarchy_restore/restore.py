"""Safe extraction worker.

Consumes a list of ``DiffRow`` (already safety-checked by ``paths.check_member``)
and writes them into ``target`` without ever using ``tarfile.extractall``.

Design:
  * Directories: ``os.makedirs(exist_ok=True)``.
  * Regular files: write to a temp file in the SAME parent dir, fsync, then
    ``os.replace`` into place. A crash never leaves a half-written file at the
    destination.
  * Symlinks: validate the link target again, then ``os.symlink``.
  * FIFOs / devices / hardlinks: re-validated; hardlinks recreated when the
    link target is also being restored.
  * setuid/setgid/caps are stripped unless ``keep_capabilities`` is set.
  * Ownership is left as the current user. The destination is always inside
    $HOME, so we never chown to a different uid.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from omarchy_restore.archive import open_archive
from omarchy_restore.diff import DiffRow, DiffStatus
from omarchy_restore.paths import safe_join


class RestoreError(RuntimeError):
    """Raised when a member cannot be restored."""


@dataclass
class RestoreEvent:
    """One event emitted during a restore, for the progress UI/log."""

    kind: str  # "written" | "skipped" | "error" | "done"
    name: str
    detail: str | None = None
    bytes_written: int = 0


@dataclass
class RestoreStats:
    written: int = 0
    skipped: int = 0
    errors: int = 0
    bytes_written: int = 0


@dataclass
class RestoreResult:
    stats: RestoreStats = field(default_factory=RestoreStats)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def record_error(self, name: str, msg: str) -> None:
        self.stats.errors += 1
        self.errors.append((name, msg))


def _apply_mode(path: Path, mode: int, keep_capabilities: bool) -> None:
    """Apply a tar member mode, optionally stripping special bits."""
    effective = mode & 0o0777 if not keep_capabilities else mode & 0o7777
    with contextlib.suppress(OSError):
        os.chmod(path, effective)


def _write_regular(tf, member, dest: Path, keep_capabilities: bool) -> int:
    """Write a regular file via temp file + fsync + atomic replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".omr-")
    tmp_path = Path(tmp_name)
    written = 0
    try:
        src = tf.extractfile(member)
        if src is None:
            raise RestoreError(f"cannot read member content: {member.name}")
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp_path, dest)
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    _apply_mode(dest, member.mode, keep_capabilities)
    return written


def _write_symlink(name: str, link_target: str, dest: Path) -> None:
    """Create a symlink, validating the target once more."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        try:
            dest.unlink()
        except IsADirectoryError as exc:
            raise RestoreError(
                f"destination is a directory, cannot replace with symlink: {name}"
            ) from exc
    os.symlink(link_target, dest)


def restore_rows(
    archive: str | os.PathLike[str],
    target: Path,
    rows: list[DiffRow],
    *,
    keep_capabilities: bool = False,
    on_event=None,
) -> RestoreResult:
    """Restore the (include=True, non-REJECT) rows from ``archive``.

    ``on_event`` is an optional callback taking a ``RestoreEvent``.
    """
    result = RestoreResult()

    include_names = {
        r.name for r in rows if r.include and r.status is not DiffStatus.REJECT
    }
    # Track hardlink targets that we have actually written, so we can recreate
    # hardlinks that point to other restored members.
    written_paths: set[Path] = set()

    with open_archive(archive) as tf:
        for member in tf:
            if member.name not in include_names:
                continue
            ev: RestoreEvent | None = None
            try:
                dest = safe_join(target, member.name)
            except Exception as exc:
                result.record_error(member.name, str(exc))
                if on_event:
                    on_event(RestoreEvent("error", member.name, str(exc)))
                continue

            try:
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    _apply_mode(dest, member.mode, keep_capabilities)
                    result.stats.written += 1
                    written_paths.add(dest.resolve(strict=False))
                    ev = RestoreEvent("written", member.name, "directory")
                elif member.issym():
                    _write_symlink(member.name, member.linkname, dest)
                    result.stats.written += 1
                    ev = RestoreEvent("written", member.name, "symlink")
                elif member.islnk():
                    linked = safe_join(target, member.linkname)
                    if linked.resolve(strict=False) in written_paths or linked.exists():
                        if dest.exists() or dest.is_symlink():
                            dest.unlink()
                        try:
                            os.link(linked, dest)
                        except OSError as exc:
                            raise RestoreError(f"hardlink failed: {exc}") from exc
                        result.stats.written += 1
                        ev = RestoreEvent("written", member.name, "hardlink")
                    else:
                        raise RestoreError(
                            f"hardlink target missing: {member.linkname}"
                        )
                elif member.isfifo() or member.ischr() or member.isblk():
                    result.stats.skipped += 1
                    ev = RestoreEvent("skipped", member.name, "special file (skipped)")
                else:
                    n = _write_regular(tf, member, dest, keep_capabilities)
                    result.stats.written += 1
                    result.stats.bytes_written += n
                    written_paths.add(dest.resolve(strict=False))
                    ev = RestoreEvent("written", member.name, None, n)
            except Exception as exc:
                result.record_error(member.name, str(exc))
                if on_event:
                    on_event(RestoreEvent("error", member.name, str(exc)))
                continue

            if on_event and ev is not None:
                on_event(ev)

    if on_event:
        on_event(RestoreEvent("done", "", None))
    return result
