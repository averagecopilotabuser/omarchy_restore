"""Diff engine: compare an archive against what's on disk.

Produces a ``DiffRow`` for every member in the archive. The diff is computed
without extracting; regular files are compared by ``(size, mtime_ns)`` first,
then a streaming ``sha256`` on mismatch.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from omarchy_restore.archive import open_archive
from omarchy_restore.omarchy import Category, categorize
from omarchy_restore.paths import SafetyVerdict, check_member


class DiffStatus(StrEnum):
    NEW = "NEW"         # not on disk
    OVERWRITE = "OVR"    # on disk, differs
    SAME = "SAME"       # on disk, identical
    OVERWRITE_DIR = "DIR"  # directory on disk that already exists
    REJECT = "REJECT"    # unsafe, will not be written


@dataclass
class DiffRow:
    name: str
    status: DiffStatus
    category: Category
    archive_size: int
    disk_size: int | None
    delta_bytes: int
    include: bool
    reason: str | None = None
    member_type: str = "file"  # file | dir | symlink | hardlink | fifo | ...
    link_target: str | None = None

    @classmethod
    def from_member(cls, member, target: Path) -> DiffRow:
        """Build a DiffRow for a tar member against the on-disk ``target``."""
        name = member.name
        is_sym = member.issym()
        is_link = member.islnk()
        if is_sym:
            mtype = "symlink"
        elif is_link:
            mtype = "hardlink"
        elif member.isdir():
            mtype = "dir"
        elif member.isfifo():
            mtype = "fifo"
        elif member.ischr() or member.isblk():
            mtype = "device"
        else:
            mtype = "file"

        category = categorize(name)

        # Safety check first.
        verdict: SafetyVerdict = check_member(
            name,
            is_symlink=is_sym,
            link_target=member.linkname if (is_sym or is_link) else None,
            is_hardlink=is_link,
            mode=member.mode,
            target=target,
        )
        if not verdict.ok:
            return cls(
                name=name,
                status=DiffStatus.REJECT,
                category=category,
                archive_size=member.size,
                disk_size=None,
                delta_bytes=member.size,
                include=False,
                reason=verdict.reason,
                member_type=mtype,
                link_target=member.linkname or None,
            )

        disk_path = (target / name).resolve(strict=False)
        disk_size: int | None = None
        delta = member.size

        if member.isdir():
            status = DiffStatus.OVERWRITE_DIR if disk_path.exists() else DiffStatus.NEW
            disk_size = None
        elif member.issym() or member.islnk():
            if disk_path.exists() or disk_path.is_symlink():
                status = DiffStatus.OVERWRITE
            else:
                status = DiffStatus.NEW
            disk_size = None
        else:
            if not disk_path.exists():
                status = DiffStatus.NEW
                disk_size = None
            else:
                try:
                    st = disk_path.stat(follow_symlinks=False)
                except OSError:
                    status = DiffStatus.NEW
                    disk_size = None
                else:
                    disk_size = st.st_size
                    delta = member.size - disk_size
                    # We cannot cheaply prove content equality from size/mtime
                    # alone (mtime is unreliable), so defer the content check
                    # to build_diff which has the archive handle for hashing.
                    if st.st_size != member.size:
                        status = DiffStatus.OVERWRITE
                    else:
                        status = DiffStatus.OVERWRITE  # provisional; refined later

        return cls(
            name=name,
            status=status,
            category=category,
            archive_size=member.size,
            disk_size=disk_size,
            delta_bytes=delta,
            include=category.default_include,
            member_type=mtype,
            link_target=member.linkname or None,
        )


# --- High level API --------------------------------------------------------


@dataclass
class DiffResult:
    rows: list[DiffRow] = field(default_factory=list)
    error: str | None = None

    def by_status(self, status: DiffStatus) -> list[DiffRow]:
        return [r for r in self.rows if r.status is status]

    def included(self) -> list[DiffRow]:
        return [r for r in self.rows if r.include and r.status is not DiffStatus.REJECT]

    def summary(self) -> dict:
        out: dict[str, int] = {s.name: 0 for s in DiffStatus}
        for r in self.rows:
            out[r.status.name] += 1
        out["total"] = len(self.rows)
        out["included_bytes"] = sum(
            r.archive_size for r in self.rows if r.include and r.status is not DiffStatus.REJECT
        )
        return out


def compare_member_content(
    disk_path: Path, member, tarfile_obj
) -> bool:
    """Return True iff the on-disk file content equals the member content."""
    h = hashlib.sha256()
    try:
        with disk_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return False

    m = hashlib.sha256()
    try:
        fobj = tarfile_obj.extractfile(member)
        if fobj is None:
            return False
        for chunk in iter(lambda: fobj.read(1 << 20), b""):
            m.update(chunk)
    except (OSError, tarfile.TarError):
        return False
    return h.digest() == m.digest()


def build_diff(archive: str | os.PathLike[str], target: Path) -> DiffResult:
    """Compute the full diff for an archive against ``target``."""
    result = DiffResult()
    try:
        with open_archive(archive) as tf:
            for member in tf:
                row = DiffRow.from_member(member, target)
                # For regular files flagged OVERWRITE with matching size, we
                # refine to SAME via a streaming sha256 comparison.
                if (
                    row.status is DiffStatus.OVERWRITE
                    and row.member_type == "file"
                    and row.disk_size == row.archive_size
                ):
                    disk_path = (target / member.name).resolve(strict=False)
                    if compare_member_content(disk_path, member, tf):
                        row.status = DiffStatus.SAME
                        row.delta_bytes = 0
                result.rows.append(row)
    except (FileNotFoundError, tarfile.ReadError, OSError) as exc:
        result.error = str(exc)
    return result
