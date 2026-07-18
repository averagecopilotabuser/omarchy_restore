#!/usr/bin/env python3
"""CLI entry point for omarchy-restore.

Usage:

    omarchy-restore [archive.tar.xz]
        [--target DIR]
        [--dry-run] [--diff-only] [--yes]
        [--theme NAME] [--no-theme] [--print-theme] [--watch-theme]
        [--keep-capabilities] [--no-color]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omarchy_restore.diff import build_diff
from omarchy_restore.paths import resolve_target
from omarchy_restore.tui.theme import (
    load_active_theme,
    load_theme_by_name,
    palette_is_monotonic,
    to_css_vars,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omarchy-restore",
        description="A safe, theme-aware TUI to restore a home-directory"
        " tar.xz backup onto a fresh Omarchy install.",
    )
    p.add_argument("archive", nargs="?", help="Path to home.tar.xz")
    p.add_argument("--target", default="", help="Target directory (default: $HOME)")
    p.add_argument("--dry-run", action="store_true", help="Preview and exit")
    p.add_argument("--diff-only", action="store_true", help="Print diff report and exit")
    p.add_argument("--yes", action="store_true", help="Skip confirmation")
    p.add_argument("--theme", help="Load a specific Omarchy theme by name")
    p.add_argument("--no-theme", action="store_true", help="Use monochrome fallback")
    p.add_argument("--print-theme", action="store_true", help="Print resolved theme and exit")
    p.add_argument("--watch-theme", action="store_true", help="Re-read theme on change")
    p.add_argument("--keep-capabilities", action="store_true", help="Preserve setuid/setgid bits")
    p.add_argument("--no-color", action="store_true", help="Disable color output")
    return p


def print_diff_report(archive: str, target: str) -> None:
    """Print a diff report in plain text for scripting use."""
    result = build_diff(archive, Path(target))
    if result.error:
        print(f"ERROR: {result.error}", file=sys.stderr)
        sys.exit(1)
    for row in result.rows:
        mark = "+" if row.include else " "
        status = row.status.value
        cat = row.category.value
        reason = f"  [{row.reason}]" if row.reason else ""
        print(f"{mark} {status:6s} {cat} {row.name}{reason}")
    s = result.summary()
    print(
        f"\n{s['NEW']} new  {s['OVERWRITE']} overwrite  {s['SAME']} unchanged  "
        f"{s['REJECT']} rejected  {s['total']} total  "
        f"{s['included_bytes']} bytes to write",
    )


def main() -> None:
    args = build_parser().parse_args()

    # — handle non-interactive commands first —
    if args.print_theme:
        theme = load_active_theme() if not args.theme else load_theme_by_name(args.theme)
        print(to_css_vars(theme))
        print(
            f"Monotonic: {palette_is_monotonic(theme)}",
            file=sys.stderr,
        )
        return

    if args.diff_only or args.dry_run:
        archive = args.archive or ""
        if not archive:
            print("ERROR: --diff-only/--dry-run requires an archive path", file=sys.stderr)
            sys.exit(1)
        target = args.target or str(Path.home())
        resolve_target(target)
        print_diff_report(archive, target)
        return

    # — launch the TUI —
    from omarchy_restore.tui.screens import OmarchyRestoreApp

    app = OmarchyRestoreApp()

    # Pre-set archive/target if provided on CLI
    if args.archive:
        ap = Path(args.archive)
        app.archive_path = str(ap.resolve() if ap.exists() else ap)
    if args.target:
        app.target_path = args.target

    app.run()


if __name__ == "__main__":
    main()
