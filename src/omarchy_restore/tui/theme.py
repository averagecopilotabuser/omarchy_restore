"""Theme loading: derive a 10-color palette from the active Omarchy theme,
with a monochrome fallback.

Public surface:

    Theme              -- frozen dataclass of CSS variable values
    load_active_theme  -- returns Theme; tries omarchy CLI, then theme.json,
                           then the monochrome fallback
    load_theme_by_name -- loads ~/.config/omarchy/themes/<NAME>/theme.json
    MONOCHROME         -- the constant fallback palette
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- The palette dataclass --------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """A 10-color palette. Every value is a CSS color string (#RRGGBB)."""

    name: str
    bg: str            # app background
    bg_panel: str      # cards, tables, inputs
    bg_elevated: str   # hover, selected, focused input
    border: str        # inactive dividers
    border_active: str # focused panel border
    fg: str            # primary text
    fg_dim: str        # secondary text
    fg_mute: str       # labels, hints
    accent: str        # one accent for the "current step" affordance
    accent_soft: str   # softer version of accent

    def as_dict(self) -> dict[str, str]:
        return {
            "bg": self.bg,
            "bg-panel": self.bg_panel,
            "bg-elevated": self.bg_elevated,
            "border": self.border,
            "border-active": self.border_active,
            "fg": self.fg,
            "fg-dim": self.fg_dim,
            "fg-mute": self.fg_mute,
            "accent": self.accent,
            "accent-soft": self.accent_soft,
        }


# --- Monochrome fallback (opencode warm-monochrome look) -------------------


MONOCHROME = Theme(
    name="monochrome",
    bg="#1A1818",
    bg_panel="#211E1E",
    bg_elevated="#2A2727",
    border="#4B4646",
    border_active="#B7B1B1",
    fg="#F1ECEC",
    fg_dim="#B7B1B1",
    fg_mute="#656363",
    accent="#E8E2DD",
    accent_soft="#CFCECD",
)


# --- Color helpers ----------------------------------------------------------


def _hex_color(value: str) -> str:
    """Normalize a color string to ``#RRGGBB``. Accepts ``#RRGGBB``,
    ``#RGB``, ``rgb(R,G,B)``, or ``RRGGBB`` (no leading #). Falls back to
    a neutral grey on parse failure."""
    v = value.strip()
    if v.startswith("#"):
        v = v[1:]
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if v.lower().startswith("rgb"):
        # very crude parser
        inside = v[v.find("(") + 1 : v.find(")")]
        parts = [p.strip() for p in inside.split(",")][:3]
        try:
            r, g, b = (int(float(p)) for p in parts)
            v = f"{r:02x}{g:02x}{b:02x}"
        except ValueError:
            return "#808080"
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        return "#808080"
    return f"#{v.lower()}"


def _hex_to_rgb(hexstr: str) -> tuple[int, int, int]:
    h = hexstr.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(hexstr: str) -> float:
    """Return the relative luminance (0..1) of a #RRGGBB color."""
    r, g, b = _hex_to_rgb(hexstr)
    vals = [c / 255.0 for c in (r, g, b)]
    out: list[float] = []
    for v in vals:
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    r1, g1, b1 = out
    return 0.2126 * r1 + 0.7152 * g1 + 0.0722 * b1


def _blend(a: str, b: str, t: float) -> str:
    """Linear blend of two #RRGGBB colors. t=0 returns a, t=1 returns b."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return _rgb_to_hex(r, g, bl)


# --- Omarchy theme parsing --------------------------------------------------


def _parse_omarchy_theme(raw: dict[str, Any]) -> Theme:
    """Build a Theme from an Omarchy theme dict.

    Omarchy themes expose colors under different keys depending on version.
    We look for the most common ones and fall back to derivations.
    """
    # Common Omarchy theme keys (vary by version):
    #   "background", "background_alt", "foreground", "foreground_alt",
    #   "cursor", "selection_text", "selection_background", "border",
    #   or "colors": { "bg": ..., "fg": ..., ... }
    colors = raw.get("colors", {}) if isinstance(raw.get("colors"), dict) else raw

    def pick(*keys: str, default: str = "#808080") -> str:
        for k in keys:
            v = colors.get(k)
            if isinstance(v, str):
                return _hex_color(v)
        return default

    bg = pick("background", "bg", default="#1A1818")
    fg = pick("foreground", "fg", default="#F1ECEC")
    fg_dim = pick("foreground_alt", "foreground-alt", "fg_alt", default=fg)
    cursor = pick("cursor", default=fg_dim)
    border = pick("border", "color8", default=fg_dim)

    # Derive the background half of the scale consistently, regardless of
    # which Omarchy key is lighter. We interpolate between bg and border so
    # that bg <= bg_panel <= bg_elevated <= border always holds.
    #   bg_panel  = 40% of the way from bg to border
    #   bg_elevated = 70% of the way from bg to border
    bg_panel = _blend(bg, border, 0.4)
    bg_elevated = _blend(bg, border, 0.7)

    # Use the cursor color as the active border; if cursor is too close to
    # the inactive border, lift it a bit toward fg.
    border_active = cursor
    if _relative_luminance(border_active) - _relative_luminance(border) < 0.05:
        border_active = _blend(border, fg, 0.6)

    # Accent: the brighter of cursor or fg.
    accent = cursor if _relative_luminance(cursor) > _relative_luminance(fg) else fg
    accent_soft = _blend(accent, bg, 0.25)

    return Theme(
        name=str(raw.get("name", "omarchy")),
        bg=bg,
        bg_panel=bg_panel,
        bg_elevated=bg_elevated,
        border=border,
        border_active=border_active,
        fg=fg,
        fg_dim=fg_dim,
        fg_mute=_blend(fg, bg, 0.55),
        accent=accent,
        accent_soft=accent_soft,
    )


# --- Loaders ----------------------------------------------------------------


def _omarchy_theme_json_path() -> Path | None:
    p = Path.home() / ".config" / "omarchy" / "current" / "theme.json"
    return p if p.exists() else None


def _themes_root() -> Path:
    return Path.home() / ".config" / "omarchy" / "themes"


def load_active_theme() -> Theme:
    """Return the active Omarchy theme as a Theme, or the monochrome fallback.

    Tries, in order:
        1. ``omarchy theme current --json`` (preferred)
        2. ``~/.config/omarchy/current/theme.json`` (cached by Omarchy)
        3. MONOCHROME fallback
    """
    # 1. CLI
    if shutil.which("omarchy"):
        try:
            out = subprocess.run(
                ["omarchy", "theme", "current", "--json"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            data = json.loads(out.stdout)
            return _parse_omarchy_theme(data)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # 2. theme.json
    p = _omarchy_theme_json_path()
    if p is not None:
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return _parse_omarchy_theme(data)
        except (OSError, json.JSONDecodeError):
            pass

    return MONOCHROME


def load_theme_by_name(name: str) -> Theme:
    """Load a specific Omarchy theme by directory name."""
    root = _themes_root() / name / "theme.json"
    if not root.exists():
        return MONOCHROME
    try:
        with root.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return MONOCHROME
    return _parse_omarchy_theme(data)


# --- CSS export -------------------------------------------------------------


def to_css_vars(theme: Theme) -> str:
    """Render a Theme as a Textual CSS ``:root { ... }`` block."""
    lines = [":root {"]
    for k, v in theme.as_dict().items():
        lines.append(f"  {k}: {v};")
    lines.append("}")
    return "\n".join(lines) + "\n"


# --- Sanity check ----------------------------------------------------------


def palette_is_monotonic(theme: Theme) -> bool:
    """Return True if the background half of the scale is monotonic in
    perceived brightness: ``bg <= bg_panel <= bg_elevated <= border``.

    The foreground half (border_active, fg, fg_dim, accent) is allowed to
    be in any order, since the active-border is often a bright accent and
    accent may be lighter than fg.
    """
    order = [theme.bg, theme.bg_panel, theme.bg_elevated, theme.border]
    lums = [_relative_luminance(c) for c in order]
    return all(lums[i] <= lums[i + 1] for i in range(len(lums) - 1))


__all__ = [
    "MONOCHROME",
    "Theme",
    "_blend",
    "_hex_color",
    "_relative_luminance",
    "load_active_theme",
    "load_theme_by_name",
    "palette_is_monotonic",
    "to_css_vars",
]
