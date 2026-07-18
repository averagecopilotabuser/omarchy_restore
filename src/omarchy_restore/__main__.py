#!/usr/bin/env python3
"""CLI entry point for omarchy-restore.

Usage:

    omarchy-restore [restore|backup] ...

    SUBCOMMANDS:

        restore [archive.tar.xz]           Restore a backup (default)
            [--target DIR]                 Target directory (default: $HOME)
            [--dry-run]                    Preview and exit
            [--diff-only]                  Print diff report as text
            [--yes]                        Skip confirmation
            [--theme NAME]                 Load a specific Omarchy theme
            [--no-theme]                   Use monochrome fallback
            [--watch-theme]                Re-read theme every 2 s
            [--keep-capabilities]          Preserve setuid/setgid/sticky bits
            [--no-color]                   Disable ANSI color in --diff-only

        backup [source]                    Create a backup archive
            [--output, -o ARCHIVE]         Output path (default: timestamped)
            [--dry-run]                    Scan and print summary, no archive
            [--yes]                        Skip confirmation
            [--theme NAME]                 Load a specific Omarchy theme
            [--no-theme]                   Use monochrome fallback

    GLOBAL FLAGS:

        --print-theme                      Print resolved theme palette, exit
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


def _add_restore_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("archive", nargs="?", help="Path to home.tar.xz")
    p.add_argument("--target", default="", help="Target directory (default: $HOME)")
    p.add_argument("--dry-run", action="store_true", help="Preview and exit")
    p.add_argument("--diff-only", action="store_true", help="Print diff report and exit")
    p.add_argument("--yes", action="store_true", help="Skip confirmation")
    p.add_argument("--theme", help="Load a specific Omarchy theme by name")
    p.add_argument("--no-theme", action="store_true", help="Use monochrome fallback")
    p.add_argument("--watch-theme", action="store_true", help="Re-read theme on change")
    p.add_argument("--keep-capabilities", action="store_true", help="Preserve setuid/setgid bits")
    p.add_argument("--no-color", action="store_true", help="Disable color output")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omarchy-restore",
        description="A safe, theme-aware TUI for Omarchy backup and restore.",
    )
    p.add_argument("--print-theme", action="store_true", help="Print resolved theme and exit")

    sub = p.add_subparsers(dest="mode")

    r = sub.add_parser("restore", help="Restore a backup archive")
    _add_restore_args(r)

    b = sub.add_parser("backup", help="Create a backup archive")
    b.add_argument("source", nargs="?", default="", help="Source directory (default: $HOME)")
    b.add_argument("-o", "--output", default="", help="Output archive path")
    b.add_argument("--dry-run", action="store_true", help="Scan and print summary, no archive")
    b.add_argument("--yes", action="store_true", help="Skip confirmation")
    b.add_argument("--theme", help="Load a specific Omarchy theme by name")
    b.add_argument("--no-theme", action="store_true", help="Use monochrome fallback")
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


def _print_theme_from_args(args) -> None:
    theme = load_active_theme() if not args.theme else load_theme_by_name(args.theme)
    print(to_css_vars(theme))
    print(f"Monotonic: {palette_is_monotonic(theme)}", file=sys.stderr)


def _handle_restore(args) -> None:
    if args.diff_only or args.dry_run:
        archive = args.archive or ""
        if not archive:
            print("ERROR: --diff-only/--dry-run requires an archive path", file=sys.stderr)
            sys.exit(1)
        target = args.target or str(Path.home())
        resolve_target(target)
        print_diff_report(archive, target)
        return

    from omarchy_restore.tui.screens import OmarchyRestoreApp

    app = OmarchyRestoreApp()
    if args.archive:
        ap = Path(args.archive)
        app.archive_path = str(ap.resolve() if ap.exists() else ap)
    if args.target:
        app.target_path = args.target
    app.run()


def _handle_backup(args) -> None:
    from omarchy_restore.backup import (
        create_backup,
        default_output_name,
        scan_source,
    )
    from omarchy_restore.paths import resolve_target

    source = Path(args.source or Path.home()).expanduser()
    if not source.is_dir():
        print(f"ERROR: not a directory: {source}", file=sys.stderr)
        sys.exit(1)
    resolve_target(str(source))

    output = Path(args.output or Path.home() / default_output_name()).expanduser()

    if args.dry_run:
        stats = scan_source(source)
        print(f"Source:  {source}")
        print(f"Included files: {stats.included_files}")
        print(f"Included bytes: {stats.included_bytes}")
        print(f"Excluded:       {stats.excluded}")
        print(f"Categories:     {stats.per_category}")
        return

    if args.yes:
        result = create_backup(source, output)
        if result.errors:
            for name, err in result.errors:
                print(f"  ! {name}: {err}", file=sys.stderr)
        print(f"Created: {output}")
        print(f"Files:   {result.stats.included_files}")
        print(f"Bytes:   {result.stats.included_bytes}")
        return

    from omarchy_restore.tui.screens import OmarchyRestoreApp

    app = OmarchyRestoreApp()
    app.mode = "backup"
    app.source_path = str(source)
    app.output_path = str(output)
    app.run()


def main() -> None:
    # Handle global --print-theme before subcommand routing
    if "--print-theme" in sys.argv:
        name = None
        if "--theme" in sys.argv:
            idx = sys.argv.index("--theme")
            if idx + 1 < len(sys.argv):
                name = sys.argv[idx + 1]
        theme = load_active_theme() if not name else load_theme_by_name(name)
        print(to_css_vars(theme))
        print(f"Monotonic: {palette_is_monotonic(theme)}", file=sys.stderr)
        return

    parser = build_parser()

    # Detect subcommand; default to "restore" for backward compat
    if len(sys.argv) >= 2 and sys.argv[1] in ("restore", "backup"):
        args = parser.parse_args()
    else:
        args = parser.parse_args(["restore", *sys.argv[1:]])

    if args.mode == "restore":
        _handle_restore(args)
    elif args.mode == "backup":
        _handle_backup(args)


if __name__ == "__main__":
    main()
