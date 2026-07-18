"""Categorization tests."""

from __future__ import annotations

import pytest

from omarchy_restore.omarchy import (
    Category,
    categorize,
    list_custom_themes,
    top_level,
)


@pytest.mark.parametrize(
    "path,expected",
    [
        # Omarchy themes
        (
            ".config/omarchy/themes/my-catppuccin/backgrounds/wall.jpg",
            Category.OMARCHY_THEME,
        ),
        (
            "home/user/.config/omarchy/themes/dark-1/theme.json",
            Category.OMARCHY_THEME,
        ),
        # System config
        (".config/hypr/hyprland.conf", Category.SYSTEM_CONFIG),
        (".config/waybar/config.jsonc", Category.SYSTEM_CONFIG),
        (".config/mako/config", Category.SYSTEM_CONFIG),
        (".config/swayosd/style.css", Category.SYSTEM_CONFIG),
        (".config/walker/config.toml", Category.SYSTEM_CONFIG),
        (".config/omarchy/hooks/theme-set", Category.SYSTEM_CONFIG),
        (".config/dconf/user", Category.SYSTEM_CONFIG),
        # Terminal
        (".config/alacritty/alacritty.toml", Category.TERMINAL),
        (".config/foot/foot.ini", Category.TERMINAL),
        (".config/kitty/kitty.conf", Category.TERMINAL),
        (".config/ghostty/config", Category.TERMINAL),
        # Shell
        (".bashrc", Category.SHELL),
        (".zshrc", Category.SHELL),
        (".config/fish/config.fish", Category.SHELL),
        (".config/starship.toml", Category.SHELL),
        (".config/atuin/config.toml", Category.SHELL),
        # Editor/IDE
        (".config/nvim/init.lua", Category.EDITOR_IDE),
        (".config/helix/config.toml", Category.EDITOR_IDE),
        (".config/Code/settings.json", Category.EDITOR_IDE),
        # Secrets
        (".ssh/id_ed25519", Category.SECRETS),
        (".gnupg/openpgp-revocs.d/foo.rev", Category.SECRETS),
        (".password-store/work/database.gpg", Category.SECRETS),
        (".local/share/keyrings/login.keyring", Category.SECRETS),
        (".config/keepassxc/config.ini", Category.SECRETS),
        # Machine-specific
        (".config/pulse/default.pa", Category.MACHINE_SPECIFIC),
        (".config/bluetooth/main.conf", Category.MACHINE_SPECIFIC),
        (".config/ibus/setup", Category.MACHINE_SPECIFIC),
        (".config/fcitx5/profile", Category.MACHINE_SPECIFIC),
        (".config/gtk-3.0/settings.ini", Category.MACHINE_SPECIFIC),
        # App-state (excluded by default)
        (".cache/anything", Category.APP_STATE),
        (".local/state/something/state.db", Category.APP_STATE),
        (
            ".local/state/omarchy/migrations/migration-123",
            Category.USER_DATA,
        ),
        (".local/share/Trash/files/foo", Category.APP_STATE),
        (".config/Code/Cache/foo", Category.APP_STATE),
        (".config/Code/CachedData/abc", Category.APP_STATE),
        (".config/Code/settings.json", Category.EDITOR_IDE),
        # User-data (catch-all)
        (".cargo/config.toml", Category.USER_DATA),
        (".npmrc", Category.USER_DATA),
        (".mozilla/firefox/profile/bookmarks.html", Category.USER_DATA),
        (".claude/settings.json", Category.USER_DATA),
        (".claude.json", Category.USER_DATA),
        (".winboat/something", Category.USER_DATA),
        (".local/share/applications/foo.desktop", Category.USER_DATA),
        (".local/share/fonts/FiraCode.ttf", Category.USER_DATA),
        (".local/share/Steam/steamapps/common/foo", Category.USER_DATA),
        ("Documents/report.pdf", Category.USER_DATA),
        ("Pictures/wallpaper.png", Category.USER_DATA),
        ("Projects/myapp/main.py", Category.USER_DATA),
        ("Work/notes.md", Category.USER_DATA),
        ("go/src/main.go", Category.USER_DATA),
        ("home/user/Documents/report.pdf", Category.USER_DATA),
        ("home/user/.config/hypr/hyprland.conf", Category.SYSTEM_CONFIG),
    ],
)
def test_categorize(path: str, expected: Category) -> None:
    assert categorize(path) == expected


def test_top_level_strips_home_prefix() -> None:
    assert top_level("home/user/.config/hypr/hyprland.conf") == ".config"
    assert top_level("Documents/report.pdf") == "Documents"
    assert top_level(".bashrc") == ".bashrc"


def test_list_custom_themes() -> None:
    paths = [
        ".config/omarchy/themes/my-catppuccin/theme.json",
        ".config/omarchy/themes/my-catppuccin/backgrounds/wall.jpg",
        ".config/omarchy/themes/dark-1/theme.json",
        "home/user/.config/omarchy/themes/light-2/style.css",
        ".config/omarchy/hooks/post-update",  # not a theme
        ".config/hypr/hyprland.conf",  # not a theme
    ]
    assert list_custom_themes(paths) == ["dark-1", "light-2", "my-catppuccin"]


class TestCategoryMetadata:
    def test_default_include(self) -> None:
        for c in Category:
            if c is Category.APP_STATE:
                assert not c.default_include
            else:
                assert c.default_include

    def test_warn_categories(self) -> None:
        assert Category.SECRETS.warn
        assert Category.MACHINE_SPECIFIC.warn
        for c in Category:
            if c not in (Category.SECRETS, Category.MACHINE_SPECIFIC):
                assert not c.warn
