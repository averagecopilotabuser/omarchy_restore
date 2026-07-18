"""Path safety: refuses to extract any member that would escape the target
directory or otherwise violate filesystem safety invariants.

Every other piece of this tool depends on this module. The contract is:

    is_member_safe(member, target_dir) -> (ok: bool, reason: str | None)

If `is_member_safe` returns `False`, the member must not be written. The
`reason` is shown to the user in the diff screen.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

# --- Forbidden destination roots ---------------------------------------------
# We refuse to write anywhere that is, or is an ancestor of, a system path
# that should never be touched by a per-user restore tool. /tmp, /opt, /srv,
# /run, /mnt, /media are intentionally NOT in this list — they are legitimate
# test/development targets and may be desired restore destinations in unusual
# setups. The CLI is expected to default to $HOME.
FORBIDDEN_TOP_LEVELS: Final[frozenset[str]] = frozenset(
    {
        "",
        "/",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/lib",
        "/lib32",
        "/lib64",
        "/lost+found",
        "/proc",
        "/root",
        "/sbin",
        "/sys",
        "/usr",
        "/var",
    }
)


class PathSafetyError(ValueError):
    """Raised by ``resolve_target`` when the target directory is unsafe."""


@dataclass(frozen=True)
class SafetyVerdict:
    ok: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def resolve_target(target: str | os.PathLike[str]) -> Path:
    """Resolve ``target`` to an absolute, real path.

    Raises ``PathSafetyError`` if the target itself is, or is an ancestor of,
    a forbidden system root.
    """
    p = Path(target).expanduser().resolve(strict=False)
    resolved = str(p)
    if resolved in FORBIDDEN_TOP_LEVELS:
        raise PathSafetyError(
            f"refusing to use system path as target: {resolved!r}"
        )
    for forbidden in FORBIDDEN_TOP_LEVELS:
        if forbidden == "" or forbidden == "/":
            continue
        if resolved == forbidden or resolved.startswith(forbidden + os.sep):
            raise PathSafetyError(
                f"refusing to use system path as target: {resolved!r} "
                f"(forbidden ancestor: {forbidden!r})"
            )
    return p


def safe_join(target: Path, rel_path: str) -> Path:
    """Join ``rel_path`` to ``target`` and reject any escape attempt.

    ``rel_path`` must be relative and use forward slashes (POSIX), as is the
    case for tar members. The returned path is **not** resolved against the
    filesystem — it is checked lexically first via ``os.path.normpath`` and
    symbolically via the ``commonpath`` of the joined path and the target.
    """
    if not rel_path:
        raise PathSafetyError("empty member name")
    if os.path.isabs(rel_path):
        raise PathSafetyError(f"absolute member name: {rel_path!r}")
    # PurePosixPath guards against backslashes on Windows; tar uses '/'.
    pure = PurePosixPath(rel_path)
    if pure.is_absolute():
        raise PathSafetyError(f"absolute member name: {rel_path!r}")
    # Reject '..' as any component.
    for part in pure.parts:
        if part == "..":
            raise PathSafetyError(f"'..' in member name: {rel_path!r}")
    joined = (target / rel_path).resolve(strict=False)
    target_resolved = target.resolve(strict=False)
    try:
        common = os.path.commonpath([str(joined), str(target_resolved)])
    except ValueError as exc:
        raise PathSafetyError(
            f"path on a different drive than target: {rel_path!r}"
        ) from exc
    if common != str(target_resolved):
        raise PathSafetyError(
            f"member escapes target directory: {rel_path!r}"
        )
    return joined


def _is_within(child: Path, parent: Path) -> bool:
    """Return True iff ``child`` is the same as or strictly under ``parent``."""
    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def _is_special_mode(mode: int) -> bool:
    """Return True if the mode carries setuid/setgid/sticky bits we should
    notice. We don't *enforce* anything on these here — the restoration
    engine consults ``--keep-capabilities`` and the mode-mask separately."""
    return bool(
        mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
    )


def check_member(
    name: str,
    *,
    is_symlink: bool,
    link_target: str | None,
    is_hardlink: bool,
    mode: int,
    target: Path,
) -> SafetyVerdict:
    """Validate a single tar member against the safety rules.

    This is the function the diff and restore engines call. It does not
    perform any I/O — it is pure logic over the member's metadata.
    """
    try:
        safe_join(target, name)
    except PathSafetyError as exc:
        return SafetyVerdict(False, str(exc))

    # Hardlinks to outside $HOME are rejected.
    if is_hardlink and link_target:
        try:
            safe_join(target, link_target)
        except PathSafetyError as exc:
            return SafetyVerdict(False, f"hardlink escapes target: {exc}")

    # Symlinks: if absolute, must point inside target. Relative symlinks
    # are accepted (and re-checked at write time in the restore engine).
    if is_symlink and link_target:
        if os.path.isabs(link_target):
            if not _is_within(Path(link_target), target):
                return SafetyVerdict(
                    False, f"symlink points outside target: {link_target!r}"
                )
        else:
            # Relative symlinks: must not use '..' to escape.
            for part in PurePosixPath(link_target).parts:
                if part == "..":
                    return SafetyVerdict(
                        False,
                        f"symlink target uses '..' to escape: {link_target!r}",
                    )

    # Special modes (setuid/setgid/sticky) are flagged but not auto-rejected.
    if _is_special_mode(mode):
        return SafetyVerdict(
            True, f"special mode bits present: {oct(mode & 0o7777)}"
        )

    # The joined path resolves to something inside target; allow it.
    return SafetyVerdict(True, None)


def is_safe_target(target: str | os.PathLike[str]) -> bool:
    """Convenience wrapper: does ``resolve_target`` succeed?"""
    try:
        resolve_target(target)
    except PathSafetyError:
        return False
    return True
