"""Theme loader tests."""

from __future__ import annotations

import pytest

from omarchy_restore.tui.theme import (
    MONOCHROME,
    Theme,
    _blend,
    _hex_color,
    _parse_omarchy_theme,
    _relative_luminance,
    load_active_theme,
    load_theme_by_name,
    palette_is_monotonic,
    to_css_vars,
)


class TestHexColor:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("#1A1818", "#1a1818"),
            ("#fff", "#ffffff"),
            ("1A1818", "#1a1818"),
            ("rgb(26, 24, 24)", "#1a1818"),
            ("#invalid", "#808080"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert _hex_color(raw) == expected


class TestHelpers:
    def test_blend_endpoints(self) -> None:
        assert _blend("#000000", "#ffffff", 0.0) == "#000000"
        assert _blend("#000000", "#ffffff", 1.0) == "#ffffff"

    def test_blend_midpoint(self) -> None:
        assert _blend("#000000", "#ffffff", 0.5) == "#808080"

    def test_relative_luminance_white(self) -> None:
        assert _relative_luminance("#ffffff") == pytest.approx(1.0, abs=0.01)

    def test_relative_luminance_black(self) -> None:
        assert _relative_luminance("#000000") == pytest.approx(0.0, abs=0.01)


class TestParseOmarchyTheme:
    def test_omarchy_v1_keys(self) -> None:
        raw = {
            "name": "tokyo-night",
            "background": "#1A1B26",
            "background_alt": "#16161E",
            "foreground": "#C0CAF5",
            "foreground_alt": "#9AA5CE",
            "cursor": "#C0CAF5",
            "selection_background": "#283457",
            "selection_text": "#C0CAF5",
            "border": "#3B4261",
        }
        t = _parse_omarchy_theme(raw)
        assert t.name == "tokyo-night"
        assert t.bg == "#1a1b26"
        assert t.fg == "#c0caf5"
        # The 6-step scale should be monotonic.
        assert palette_is_monotonic(t)

    def test_omarchy_v2_nested_colors(self) -> None:
        raw = {
            "name": "catppuccin",
            "colors": {
                "bg": "#1E1E2E",
                "fg": "#CDD6F4",
                "cursor": "#F5E0DC",
                "border": "#45475A",
            },
        }
        t = _parse_omarchy_theme(raw)
        assert t.name == "catppuccin"
        assert t.bg == "#1e1e2e"
        assert t.fg == "#cdd6f4"
        assert palette_is_monotonic(t)

    def test_minimal_keys_falls_back(self) -> None:
        # No recognized keys at all — must still produce a valid palette.
        t = _parse_omarchy_theme({})
        # Default colors are pulled, monotonicity still holds.
        assert palette_is_monotonic(t)

    def test_known_themes_all_monotonic(self) -> None:
        # Synthetic but representative palettes for the 4 stock Omarchy themes.
        for name, bg, fg, cursor, border in [
            ("tokyo-night", "#1A1B26", "#C0CAF5", "#C0CAF5", "#3B4261"),
            ("catppuccin", "#1E1E2E", "#CDD6F4", "#F5E0DC", "#45475A"),
            ("gruvbox", "#282828", "#EBDBB2", "#EBDBB2", "#3C3836"),
            ("nord", "#2E3440", "#ECEFF4", "#88C0D0", "#3B4252"),
        ]:
            t = _parse_omarchy_theme(
                {
                    "name": name,
                    "background": bg,
                    "foreground": fg,
                    "cursor": cursor,
                    "border": border,
                }
            )
            # bg <= bg_panel <= bg_elevated <= border must hold
            assert palette_is_monotonic(t), f"non-monotonic palette: {name}"


class TestLoaders:
    def test_load_active_returns_a_theme(self) -> None:
        t = load_active_theme()
        assert isinstance(t, Theme)
        assert palette_is_monotonic(t)

    def test_load_by_name_missing_returns_mono(self) -> None:
        t = load_theme_by_name("definitely-not-a-theme-xyz")
        assert t == MONOCHROME


class TestCSSExport:
    def test_to_css_vars_contains_all_keys(self) -> None:
        css = to_css_vars(MONOCHROME)
        for k in MONOCHROME.as_dict():
            assert k in css
        assert ":root" in css
        assert MONOCHROME.bg in css


class TestMonochromeIsMonotonic:
    def test_monochrome_passes(self) -> None:
        assert palette_is_monotonic(MONOCHROME)
