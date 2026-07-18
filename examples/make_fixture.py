#!/usr/bin/env python3
"""Build a small tar.xz fixture for manual testing.

Usage:
    python examples/make_fixture.py [output.tar.xz]

Default output: /tmp/omarchy-restore-fixture.tar.xz
"""

from __future__ import annotations

import io
import os
import tarfile
import time
import sys
from pathlib import Path


def make_fixture(output: str | os.PathLike[str]) -> Path:
    """Build a representative Omarchy home-directory fixture."""

    def _add(tf, name, **kw):
        data = kw.pop("data", b"")
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mode = kw.pop("mode", 0o644)
        info.mtime = int(time.time())
        info.type = kw.pop("type", tarfile.REGTYPE)
        if "linkname" in kw:
            info.linkname = kw.pop("linkname")
        for k, v in kw.items():
            setattr(info, k, v)
        tf.addfile(info, fileobj=io.BytesIO(data) if data else None)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:xz") as tf:
        # Personal data
        _add(tf, "Documents/notes.txt", data=b"My important notes\n")
        _add(tf, "Documents/todo.md", data=b"- buy milk\n")
        _add(tf, "Pictures/selfie.png", data=b"\x89PNG...\n")
        _add(tf, "Videos/trip.mp4", data=b"fakedata")

        # Dotfiles
        _add(tf, ".bashrc", data=b'alias ll="ls -la"\n')
        _add(tf, ".ssh/id_ed25519", data=b"PRIVATE_KEY\n", mode=0o600)

        # Omarchy themes
        _add(
            tf,
            ".config/omarchy/themes/my-custom/theme.json",
            data=b'{"name": "my-custom", "colors": {"bg": "#111", "fg": "#eee"}}\n',
        )
        _add(
            tf,
            ".config/omarchy/themes/my-custom/backgrounds/wall.jpg",
            data=b"wallpaper",
        )

        # Omarchy config
        _add(tf, ".config/hypr/hyprland.conf", data=b"monitor=,preferred,auto,1\n")
        _add(tf, ".config/waybar/config.jsonc", data=b'{"layer": "top"}\n')

        # Terminal config
        _add(tf, ".config/alacritty/alacritty.toml", data=b"[font]\nsize = 11\n")

        # Shell config
        _add(tf, ".config/starship.toml", data=b'add_newline = false\n')

        # Editor
        _add(tf, ".config/nvim/init.lua", data=b"-- neovim config\n")

        # Caches (should be excluded by default)
        _add(tf, ".cache/thumbnails/big.jpg", data=b"\x00" * 10)

        # App state (should be excluded)
        _add(tf, ".local/state/something.db", data=b"state")

        # Machine-specific (warn)
        _add(tf, ".config/pulse/default.pa", data=b"load-module module-native-protocol-unix\n")

        # User data
        _add(tf, ".cargo/config.toml", data=b"[registries.crates-io]\n")
        _add(tf, ".local/share/applications/custom.desktop", data=b"[Desktop Entry]\n")
        _add(tf, ".local/share/fonts/FiraCode.ttf", data=b"\x00" * 100)

    return out


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/omarchy-restore-fixture.tar.xz"
    path = make_fixture(out)
    sz = path.stat().st_size
    print(f"Created {path} ({sz} bytes)")
