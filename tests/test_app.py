"""Quick app tests: verify bootstrap, CLI help, and diff-report output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from omarchy_restore.__main__ import build_parser
from omarchy_restore.archive import archive_summary
from omarchy_restore.tui.theme import load_active_theme


class TestCLI:
    def test_help_flag(self) -> None:
        """Verify --help raises SystemExit (expected behavior)."""
        p = build_parser()
        # The --help flag triggers SystemExit in argparse. Verify our parser
        # is properly configured by testing a normal parse.
        args = p.parse_args(["--print-theme"])
        assert args.print_theme
        # Verify --help exits as expected (positive test of argparse behavior)
        with pytest.raises(SystemExit):
            p.parse_args(["--help"])

    def test_print_theme(self) -> None:
        theme = load_active_theme()
        assert theme.name
        # We don't call --print-theme on CLI because it prints to stdout;
        # just verify it resolves.

    def test_diff_only_with_fixture(self, tmp_path: Path) -> None:
        """Use make_fixture to create a tar.xz and run --diff-only."""
        from examples.make_fixture import make_fixture

        archive = make_fixture(tmp_path / "fixture.tar.xz")
        target = tmp_path / "target"
        target.mkdir()

        # Run omarchy-restore --diff-only via subprocess (simulating CLI).
        # Build the entry point manually:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "omarchy_restore",
                "--diff-only",
                str(archive),
                "--target",
                str(target),
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        if result.returncode != 0:
            print("STDERR:", result.stderr)
        assert result.returncode == 0
        assert ".ssh/id_ed25519" in result.stdout


class TestArchiveSummary:
    def test_fixture_summary(self, tmp_path: Path) -> None:
        from examples.make_fixture import make_fixture

        archive = make_fixture(tmp_path / "test.tar.xz")
        s = archive_summary(archive)
        assert s["total_members"] > 0
        assert s["files"] > 0
        assert "Documents" in s["top_level"]
