"""Categorize archive member paths into Omarchy-aware buckets.

The order of rules matters: more specific rules win over less specific ones.
The catch-all ``user-data`` category is last so anything that doesn't match a
more specific rule ends up in the safe default-included bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    """Categories used by the TUI's filters and category chips.

    The string value is the single-letter chip shown in the diff table.
    """

    OMARCHY_THEME = "O"        # ~/.config/omarchy/themes/<name>
    SYSTEM_CONFIG = "S"        # hypr, waybar, mako, swayosd, walker, omarchy/
    TERMINAL = "T"             # alacritty, foot, kitty, ghostty
    SHELL = "H"                # bash, fish, zsh, starship, atuin
    EDITOR_IDE = "E"           # code, code-oss, helix, nvim, vim
    SECRETS = "K"              # ssh, gnupg, password-store, keyrings
    MACHINE_SPECIFIC = "M"     # monitors, pulse, bluetooth, ibus, fcitx5
    APP_STATE = "A"            # caches, transient state
    USER_DATA = "\u00b7"       # catch-all; included by default

    @property
    def label(self) -> str:
        return {
            Category.OMARCHY_THEME: "omarchy-theme",
            Category.SYSTEM_CONFIG: "system-config",
            Category.TERMINAL: "terminal",
            Category.SHELL: "shell",
            Category.EDITOR_IDE: "editor/ide",
            Category.SECRETS: "secrets",
            Category.MACHINE_SPECIFIC: "machine-specific",
            Category.APP_STATE: "app-state",
            Category.USER_DATA: "user-data",
        }[self]

    @property
    def default_include(self) -> bool:
        return self not in {Category.APP_STATE}

    @property
    def warn(self) -> bool:
        """If True, the TUI shows a warning chip in the confirm screen."""
        return self in {Category.SECRETS, Category.MACHINE_SPECIFIC}


@dataclass(frozen=True)
class PathMatch:
    category: Category
    matched_pattern: str | None = None


# --- Pattern tables --------------------------------------------------------
# Patterns are POSIX-style prefixes relative to the archive root. If the
# archive was created from "/" the member names will look like
# "home/user/...". If from "$HOME" they will look like ".config/..." or
# "Documents/...". We handle both by stripping a common leading "home/<user>/"
# or "$HOME/" before categorizing.

_LEADING_HOME_REDACTIONS = (
    "home/",  # generic; we do not assume a specific username
)

# Patterns are (category, [list of (substr, matched) checks]). For each
# category, the path must match one of the substrs at the *start* of the
# path. A category matches if any of its substrs is a prefix of the path.

_PATTERNS: list[tuple[Category, tuple[str, ...]]] = [
    # Omarchy themes get their own category so the diff screen groups them.
    (Category.OMARCHY_THEME, (".config/omarchy/themes/",)),
    # System config: each subsystem gets the same label.
    (
        Category.SYSTEM_CONFIG,
        (
            ".config/hypr/",
            ".config/waybar/",
            ".config/mako/",
            ".config/swayosd/",
            ".config/walker/",
            ".config/omarchy/",
            ".config/dconf/",
        ),
    ),
    # Terminals
    (
        Category.TERMINAL,
        (
            ".config/alacritty/",
            ".config/foot/",
            ".config/kitty/",
            ".config/ghostty/",
        ),
    ),
    # Shell
    (
        Category.SHELL,
        (
            ".bashrc",
            ".bash_profile",
            ".bash_login",
            ".bash_logout",
            ".bash_aliases",
            ".profile",
            ".zshrc",
            ".zprofile",
            ".zshenv",
            ".config/bash/",
            ".config/fish/",
            ".config/zsh/",
            ".config/starship.toml",
            ".config/atuin/",
        ),
    ),
    # Editor/IDE
    (
        Category.EDITOR_IDE,
        (
            ".config/nvim/",
            ".config/helix/",
            ".config/vim/",
            ".config/vscode/",
            ".config/Code/",
            ".config/code-oss/",
            ".config/codium/",
        ),
    ),
    # Secrets — must precede user-data
    (
        Category.SECRETS,
        (
            ".ssh/",
            ".gnupg/",
            ".password-store/",
            ".local/share/keyrings/",
            ".local/share/gnupg/",
            ".pki/",
            ".config/keepassxc/",
        ),
    ),
    # Machine-specific: usually different on a new machine, but the user
    # said "all my stuff back" so we include with a warning.
    (
        Category.MACHINE_SPECIFIC,
        (
            ".config/pulse/",
            ".config/bluetooth/",
            ".config/ibus/",
            ".config/fcitx5/",
            ".config/xsettingsd/",
            ".config/monitors.conf",
            ".config/gtk-3.0/",
            ".config/gtk-4.0/",
            ".config/qt5ct/",
            ".config/qt6ct/",
        ),
    ),
]

# App-state subtrees. More specific entries win over the catch-all. We allow
# non-app-state siblings in the same parent by being prefix-exact: e.g.
# ``.local/state/omarchy/`` is *not* app-state because omarchy stores
# user-level state there. We handle that via the ``_STATE_EXCEPTIONS`` table.
_APP_STATE_PREFIXES: tuple[str, ...] = (
    ".cache/",
    ".local/state/",
    ".local/share/Trash/",
    ".local/share/gvfs-metadata/",
    ".local/share/recently-used.xbel",
    ".local/share/xorg/",
)
_STATE_EXCEPTIONS: frozenset[str] = frozenset(
    {
        # Omarchy user state is included.
        ".local/state/omarchy/",
        # User-installed fonts, .desktop files etc. are data, not cache.
        ".local/share/fonts/",
        ".local/share/applications/",
        # App data dirs (Steam, Lutris, Anki, etc.) are data, not state.
        ".local/share/Steam/",
        ".local/share/lutris/",
        ".local/share/Anki2/",
        ".local/share/Balatro/",
        ".local/share/unity3d/",
        ".local/share/PrismLauncher/",
        ".local/share/multimc/",
        ".local/share/ModrinthApp/",
    }
)

# Specific app-state subtrees that live *under* categorized configs (e.g.
# ``.config/Code/Cache/``). These are checked before per-category rules so
# they correctly demote to app-state.
_APP_STATE_SPECIFIC: tuple[str, ...] = (
    ".config/Code/Cache/",
    ".config/Code/CachedData/",
    ".config/Code/GPUCache/",
    ".config/Code/Code Cache/",
    ".config/Code/blob_storage/",
    ".config/Code/IndexedDB/",
    ".config/Code/Service Worker/",
    ".config/Code/Local Storage/leveldb/",
    ".config/Code - OSS/Cache/",
    ".config/Code - OSS/CachedData/",
    ".config/Code - OSS/GPUCache/",
    ".config/Code - OSS/Code Cache/",
    ".config/chromium/Cache/",
    ".config/chromium/CachedData/",
    ".config/chromium/GPUCache/",
    ".config/chromium/blob_storage/",
    ".config/chromium/IndexedDB/",
)

# Top-level directories that are always user-data even though they don't
# start with a dot.
_USER_DATA_DIRS: frozenset[str] = frozenset(
    {
        "Documents",
        "Downloads",
        "Music",
        "Pictures",
        "Videos",
        "Projects",
        "Work",
        "Desktop",
        "Templates",
        "Public",
        "go",
        "winboat",
    }
)


def _normalize(rel_path: str) -> str:
    """Return a path normalized for matching against the pattern tables.

    We expect POSIX-style forward slashes. We strip a leading ``./`` and any
    leading ``home/<user>/`` redaction so that an archive created with
    ``tar -czf home.tar.xz -C /home/user .`` matches the same patterns as one
    created with ``tar -czf home.tar.xz -C / .``.
    """
    p = rel_path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _looks_like_home_root(stripped: str) -> str:
    """If the path starts with ``home/<user>/``, strip that prefix so the
    remainder can be matched against dotfile/relative patterns.
    """
    parts = stripped.split("/", 2)
    if len(parts) >= 3 and parts[0] == "home" and parts[1]:
        # Looks like home/<user>/... — treat remainder as if relative to $HOME.
        return parts[2]
    return stripped


def categorize(rel_path: str) -> Category:
    """Return the category for an archive member path."""
    p = _normalize(rel_path)
    p = _looks_like_home_root(p)
    if not p:
        return Category.USER_DATA

    # Top-level dir matches (Documents/, Pictures/, etc.)
    first = p.split("/", 1)[0]
    if first in _USER_DATA_DIRS:
        return Category.USER_DATA

    # Specific app-state subtrees (under broader categorized configs). Check
    # first so cache subdirs of editors, browsers, etc. demote correctly.
    for prefix in _APP_STATE_SPECIFIC:
        if p.startswith(prefix):
            return Category.APP_STATE

    # App-state: check prefixes, then exceptions.
    for prefix in _APP_STATE_PREFIXES:
        if p.startswith(prefix):
            for exc in _STATE_EXCEPTIONS:
                if p.startswith(exc):
                    return Category.USER_DATA
            return Category.APP_STATE

    # Per-category pattern match (order in _PATTERNS is priority).
    for cat, prefixes in _PATTERNS:
        for prefix in prefixes:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                return cat

    return Category.USER_DATA


def top_level(path: str) -> str:
    """First path component of a (normalized) archive member."""
    p = _normalize(path)
    p = _looks_like_home_root(p)
    parts = p.split("/", 1)
    return parts[0] if parts else ""


# --- Theme directory listing ------------------------------------------------


def list_custom_themes(rel_paths: list[str]) -> list[str]:
    """Return the names of custom Omarchy themes present in the archive."""
    themes: set[str] = set()
    for p in rel_paths:
        n = _normalize(p)
        n = _looks_like_home_root(n)
        if n.startswith(".config/omarchy/themes/"):
            tail = n[len(".config/omarchy/themes/") :]
            name = tail.split("/", 1)[0]
            if name:
                themes.add(name)
    return sorted(themes)
