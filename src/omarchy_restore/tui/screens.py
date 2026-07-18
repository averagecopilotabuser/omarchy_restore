"""All 6 screens and the App root for omarchy-restore."""

from __future__ import annotations

import asyncio
import os
import tarfile
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Static,
)

from omarchy_restore.archive import archive_summary, open_archive
from omarchy_restore.diff import DiffRow, DiffStatus, build_diff
from omarchy_restore.omarchy import Category, list_custom_themes
from omarchy_restore.paths import resolve_target
from omarchy_restore.restore import RestoreEvent, restore_rows
from omarchy_restore.tui.theme import load_active_theme

# ── Helpers ────────────────────────────────────────────────────────────────


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}PB"


# ── Screen 1: Welcome ─────────────────────────────────────────────────────


class WelcomeScreen(Screen):
    CANCEL_KEY = "q"
    CSS = """
    WelcomeScreen {
        align: center middle;
    }
    .wordmark {
        text-style: bold;
        color: $fg;
        content-align: center top;
        height: 3;
    }
    .tagline {
        color: $fg-dim;
        height: 1;
        content-align: center top;
    }
    .field-label {
        color: $fg-mute;
        text-style: bold;
        height: 1;
    }
    Input {
        border: solid $border;
        background: $bg;
        color: $fg;
        padding: 0 1;
        height: 3;
        width: 40;
        margin: 0 0 1 0;
    }
    Input:focus {
        border: solid $border-active;
        background: $bg-elevated;
    }
    #scan-button {
        background: $bg-elevated;
        color: $fg;
        border: solid $border;
        padding: 0 2;
        height: 3;
        margin: 1 0 0 0;
    }
    #scan-button:focus {
        border: solid $border-active;
    }
    .error { color: $fg-dim; text-style: bold; height: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("█ █ omarchy-restore", classes="wordmark")
            yield Static("Restore your Omarchy home from a backup", classes="tagline")
            yield Static("Archive", classes="field-label")
            yield Input(placeholder="/path/to/home.tar.xz", id="archive-input")
            yield Static("Target", classes="field-label")
            yield Input(
                placeholder=os.path.expanduser("~"),
                id="target-input",
                value=os.path.expanduser("~"),
            )
            with Horizontal():
                yield Button("Scan archive", id="scan-button", variant="default")
            yield Label("", id="welcome-error", classes="error")

    @on(Button.Pressed, "#scan-button")
    async def on_scan(self) -> None:
        archive = self.query_one("#archive-input", Input).value.strip()
        target = self.query_one("#target-input", Input).value.strip()
        err = self.query_one("#welcome-error", Label)
        if not archive:
            err.update("Please enter an archive path")
            return
        if not target:
            err.update("Please enter a target directory")
            return
        archive_path = Path(archive).expanduser()
        if not archive_path.exists():
            err.update(f"Archive not found: {archive_path}")
            return
        try:
            resolve_target(target)
        except Exception as exc:
            err.update(str(exc))
            return
        try:
            with open_archive(archive_path):
                pass
        except (tarfile.ReadError, Exception) as exc:
            err.update(f"Cannot open archive: {exc}")
            return
        err.update("")
        app = self.app
        app.archive_path = str(archive_path)
        app.target_path = target
        await app.push_screen("preview")


# ── Screen 2: Preview ─────────────────────────────────────────────────────


class PreviewScreen(Screen):
    BINDINGS = [("d", "proceed_to_diff", "Diff"), ("q", "app.pop_screen", "Back")]
    CSS = """
    PreviewScreen { align: center middle; }
    #preview-summary {
        color: $fg-dim;
        margin: 1 2;
        height: auto;
    }
    #preview-error { color: $fg-dim; text-style: bold; margin: 1; }
    #diff-button {
        background: $bg-elevated;
        color: $fg;
        border: solid $border;
        padding: 0 2;
        margin: 1 0;
    }
    #diff-button:focus { border: solid $border-active; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Preview · archive summary", classes="screen-title")
            yield Static("", id="preview-summary")
            yield Static("", id="preview-error")
            yield Button("Show diff", id="diff-button", variant="primary")

    def on_mount(self) -> None:
        try:
            summary = archive_summary(self.app.archive_path)
            lines = [
                f"Members:    {summary['total_members']}",
                f"Files:      {summary['files']}",
                f"Dirs:       {summary['dirs']}",
                f"Symlinks:   {summary['symlinks']}",
                f"Uncompressed: {_format_bytes(summary['uncompressed_bytes'])}",
                "",
                "Top-level entries:",
            ]
            for t in summary["top_level"]:
                lines.append(f"  {t}")
            self.query_one("#preview-summary", Static).update("\n".join(lines))
        except Exception as exc:
            self.query_one("#preview-error", Static).update(f"Error: {exc}")

    @on(Button.Pressed, "#diff-button")
    async def proceed_to_diff(self) -> None:
        await self.app.push_screen("diff")

    def action_proceed_to_diff(self) -> None:
        self.app.push_screen("diff")


# ── Screen 3: Diff ────────────────────────────────────────────────────────


STATUS_SYMBOLS = {
    DiffStatus.NEW: "+",
    DiffStatus.OVERWRITE: "~",
    DiffStatus.SAME: "=",
    DiffStatus.OVERWRITE_DIR: "*",
    DiffStatus.REJECT: "!",
}

CATEGORY_BUTTONS: list[tuple[str, Category | None]] = [
    ("ALL", None),
    ("O", Category.OMARCHY_THEME),
    ("S", Category.SYSTEM_CONFIG),
    ("T", Category.TERMINAL),
    ("H", Category.SHELL),
    ("E", Category.EDITOR_IDE),
    ("K", Category.SECRETS),
    ("M", Category.MACHINE_SPECIFIC),
    ("A", Category.APP_STATE),
    ("·", Category.USER_DATA),
]


class DiffScreen(Screen):
    BINDINGS = [
        ("space", "toggle_row", "Toggle"),
        ("a", "select_all", "All"),
        ("/", "focus_search", "Search"),
        ("c", "confirm", "Confirm"),
        ("q", "app.pop_screen", "Back"),
    ]

    _all_rows: list[DiffRow] = []
    _filtered_rows: list[DiffRow] = []
    _active_filter: Category | None = None

    CSS = """
    #filter-row { height: 3; align: center middle; }
    .filter-btn {
        background: $bg-panel;
        color: $fg-mute;
        border: solid $border;
        min-width: 4;
        height: 3;
        margin: 0 1;
    }
    .filter-btn:focus { border: solid $border-active; color: $fg; }
    .filter-btn.active { border: solid $border-active; color: $fg; }
    DataTable {
        background: $bg-panel;
        color: $fg;
        height: 1fr;
        border: solid $border;
    }
    DataTable:focus { border: solid $border-active; }
    DataTable > .datatable--header {
        color: $fg-dim;
        background: $bg-panel;
        text-style: bold;
    }
    DataTable .datatable--cursor { background: $bg-elevated; color: $fg; }
    .help-text { color: $fg-mute; height: 1; padding: 0 2; }
    .screen-title {
        text-style: bold;
        color: $fg;
        padding: 0 2;
        height: 1;
    }
    #diff-stats { color: $fg-mute; height: 1; padding: 0 2; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Diff · per-file comparison", classes="screen-title")
        with Horizontal(id="filter-row"):
            for label, _ in CATEGORY_BUTTONS:
                yield Button(label, id=f"cat-{label.lower()}" if label != "ALL" else "cat-all", classes="filter-btn")
        yield Static("", id="diff-stats")
        yield DataTable(id="diff-table")
        yield Static("space toggle  a all  / search  c confirm", classes="help-text")

    def on_mount(self) -> None:
        self._load_diff()

    def _load_diff(self) -> None:
        self._all_rows = build_diff(
            self.app.archive_path,
            Path(self.app.target_path),
        ).rows
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._active_filter is None:
            self._filtered_rows = list(self._all_rows)
        else:
            self._filtered_rows = [
                r for r in self._all_rows if r.category is self._active_filter
            ]
        self.query_one("#diff-stats", Static).update(
            f"{len(self._filtered_rows)} files  "
            f"[+] {len([r for r in self._filtered_rows if r.include])} included  "
            f"[!] {len([r for r in self._filtered_rows if r.status is DiffStatus.REJECT])} rejected"
        )
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#diff-table", DataTable)
        table.clear(columns=True)
        table.add_columns("INCL", "STATUS", "PATH", "SIZE", "Δ", "CAT")
        for row in self._filtered_rows:
            symbol = STATUS_SYMBOLS.get(row.status, "?")
            st = f"{symbol} {row.status.value}"
            ct = row.category.value
            im = "+" if row.include else " "
            table.add_row(
                im,
                st,
                row.name[:120],
                _format_bytes(row.archive_size) if row.archive_size else "-",
                _format_bytes(abs(row.delta_bytes)),
                ct,
                key=row.name,
            )

    @on(Button.Pressed)
    def on_filter(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        for label, cat in CATEGORY_BUTTONS:
            button_id = f"cat-{label.lower()}" if label != "ALL" else "cat-all"
            if bid == button_id:
                if cat is None or self._active_filter == cat:
                    self._active_filter = None
                else:
                    self._active_filter = cat
                break
        self._apply_filter()

    @on(DataTable.RowSelected, "#diff-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None:
            return
        name = str(event.row_key.value)
        for r in self._all_rows:
            if r.name == name:
                r.include = not r.include
                break
        self._apply_filter()

    def action_toggle_row(self) -> None:
        table = self.query_one("#diff-table", DataTable)
        c = table.cursor_cell
        if c is None or c.row_key is None:
            return
        name = str(c.row_key.value)
        for r in self._all_rows:
            if r.name == name:
                r.include = not r.include
                break
        self._apply_filter()

    def action_select_all(self) -> None:
        for r in self._all_rows:
            r.include = True
        self._apply_filter()

    def action_confirm(self) -> None:
        self.app.diff_rows = self._all_rows
        self.app.push_screen("confirm")

    def action_focus_search(self) -> None:
        self.query_one("#diff-table", DataTable).focus()


# ── Screen 4: Confirm ─────────────────────────────────────────────────────


class ConfirmScreen(Screen):
    BINDINGS = [("y", "do_restore", "Y Restore"), ("q", "app.pop_screen", "Back")]
    CSS = """
    ConfirmScreen { align: center middle; }
    .screen-title { text-style: bold; color: $fg; padding: 0 2; height: 1; }
    #confirm-stats { height: auto; margin: 1 2; }
    #confirm-counts { color: $fg-dim; margin: 0 2; }
    #confirm-topdirs { color: $fg-mute; margin: 0 2; }
    #confirm-warnings { color: $fg-dim; text-style: bold; }
    .affordance {
        color: $fg-dim;
        padding: 1 2;
        text-align: center;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Confirm · ready to restore", classes="screen-title")
            yield Static("", id="confirm-counts")
            yield Static("", id="confirm-warnings")
            yield Static(
                " [reverse]Y[/] Restore  esc to go back",
                classes="affordance",
            )

    def on_mount(self) -> None:
        rows: list[DiffRow] = getattr(self.app, "diff_rows", [])
        included = [r for r in rows if r.include and r.status is not DiffStatus.REJECT]
        n_new = len([r for r in included if r.status is DiffStatus.NEW])
        n_ovr = len([r for r in included if r.status is DiffStatus.OVERWRITE])
        skipped = len([r for r in rows if not r.include and r.status is not DiffStatus.REJECT])
        total_bytes = sum(r.archive_size for r in included)
        top_dirs: set[str] = set()
        for r in included:
            top_dirs.add(r.name.split("/", 1)[0])
        self.query_one("#confirm-counts", Static).update(
            f"Files to write:  {len(included)}\n"
            f"  new:           {n_new}\n"
            f"  overwrite:     {n_ovr}\n"
            f"Skipped:        {skipped}\n"
            f"Total bytes:    {_format_bytes(total_bytes)}\n"
            + "\n".join(f"  \u203a {d}" for d in sorted(top_dirs)[:15])
        )
        warns: list[str] = []
        sc = len([r for r in included if r.category is Category.SECRETS])
        mc = len([r for r in included if r.category is Category.MACHINE_SPECIFIC])
        if sc:
            warns.append(f"\u26a0 {sc} secret files will be restored")
        if mc:
            warns.append(f"\u26a0 {mc} machine-specific files will be restored")
        self.query_one("#confirm-warnings", Static).update("\n".join(warns))

    def action_do_restore(self) -> None:
        self.app.push_screen("progress")


# ── Screen 5: Progress ────────────────────────────────────────────────────


class ProgressScreen(Screen):
    BINDINGS = [("q", "cancel_restore", "Cancel")]
    CSS = """
    ProgressScreen {
        align: center middle;
    }
    .screen-title { text-style: bold; color: $fg; padding: 0 2; height: 1; }
    ProgressBar { height: 1; margin: 1 0; }
    ProgressBar > .bar { color: $accent; }
    #progress-stats { color: $fg-dim; height: 1; }
    #progress-log {
        background: $bg-panel;
        color: $fg-dim;
        border: solid $border;
        height: 1fr;
        width: 1fr;
    }
    .help-text { color: $fg-mute; height: 1; padding: 0 2; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Restoring \u2026", classes="screen-title")
            yield ProgressBar(id="progress-bar", total=100)
            yield Static("", id="progress-stats")
            yield RichLog(id="progress-log", highlight=True, max_lines=100)
            yield Static("q cancel \u2022 restore in progress", classes="help-text")

    def on_mount(self) -> None:
        self.run_worker(self._run_restore(), exclusive=True)

    async def _run_restore(self) -> None:
        bar = self.query_one("#progress-bar", ProgressBar)
        stats = self.query_one("#progress-stats", Static)
        log = self.query_one("#progress-log", RichLog)
        bar.update(progress=0)
        rows: list[DiffRow] = getattr(self.app, "diff_rows", [])
        included = [
            r for r in rows if r.include and r.status is not DiffStatus.REJECT
        ]
        total = max(len(included), 1)
        done = 0

        def on_event(ev: RestoreEvent) -> None:
            nonlocal done
            if ev.kind == "written":
                done += 1
                try:
                    bar.update(progress=int(done / total * 100))
                    stats.update(
                        f"Written: {done} / {total}"
                    )
                except Exception:
                    pass
                log.write(f"  \u2713 {ev.name}")
            elif ev.kind == "skipped":
                log.write(f"  - {ev.name}  ({ev.detail})")
            elif ev.kind == "error":
                log.write(f"  ! {ev.name}  {ev.detail}")
            elif ev.kind == "done":
                bar.update(progress=100)
                stats.update(f"Done: {done} files written")
                log.write("\nRestore complete")

        await asyncio.get_event_loop().run_in_executor(
            None,
            restore_rows,
            self.app.archive_path,
            Path(self.app.target_path),
            rows,
            on_event=on_event,  # type: ignore[reportCallIssue]
        )
        await asyncio.sleep(0.3)
        await self.app.push_screen("done")

    def action_cancel_restore(self) -> None:
        self.app.pop_screen()


# ── Screen 6: Done ────────────────────────────────────────────────────────


class DoneScreen(Screen):
    BINDINGS = [("q", "done", "Done")]
    CSS = """
    DoneScreen { align: center middle; }
    .screen-title { text-style: bold; color: $fg; padding: 0 2; height: 1; }
    #done-summary { color: $fg-dim; margin: 1 2; height: auto; }
    .field-label { color: $fg-mute; text-style: bold; height: 1; }
    ListView {
        background: $bg-panel;
        border: solid $border;
        height: 1fr;
        width: 1fr;
    }
    .help-text { color: $fg-mute; height: 1; padding: 0 2; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Restore complete", classes="screen-title")
            yield Static("", id="done-summary")
            yield Static("Reload Omarchy components:", classes="field-label")
            yield ListView(id="reload-list")
            yield Static("q done  enter reload selected", classes="help-text")

    def on_mount(self) -> None:
        rows: list[DiffRow] = getattr(self.app, "diff_rows", [])
        written = [r for r in rows if r.include and r.status is not DiffStatus.REJECT]
        self.query_one("#done-summary", Static).update(
            f"Files written:  {len(written)}\n"
            f"Total bytes:    {_format_bytes(sum(r.archive_size for r in written))}"
        )
        touched_names = [r.name for r in written]
        touched_all = " ".join(touched_names)
        reload_items: list[tuple[str, str]] = []
        if "hypr/" in touched_all:
            reload_items.append(("Reload Hyprland", "hyprctl reload"))
        if "waybar/" in touched_all:
            reload_items.append(("Restart Waybar", "omarchy restart waybar"))
        if any(t in touched_all for t in ("alacritty/", "foot/", "kitty/", "ghostty/")):
            reload_items.append(("Restart terminal", "omarchy restart terminal"))
        if "walker/" in touched_all:
            reload_items.append(("Restart Walker", "omarchy restart walker"))
        theme_names = list_custom_themes(touched_names)
        for tn in theme_names:
            reload_items.append((f"Set theme: {tn}", f'omarchy theme set "{tn}"'))
        lv = self.query_one("#reload-list", ListView)
        for label, _cmd in reload_items:
            lv.append(ListItem(Label(f"  [ ]  {label}")))

    def action_done(self) -> None:
        self.app.pop_screen()


# ── App root ───────────────────────────────────────────────────────────────


CSS_TEMPLATE = """/* omarchy-restore tcss — colors injected at runtime */

:root {{
{vars}
}}

Screen {{
  background: $bg;
  color: $fg;
}}

Static.screen-title {{
  text-style: bold;
  color: $fg;
  padding: 0 2;
  height: 1;
}}

.help-text {{
  color: $fg-mute;
  height: 1;
  padding: 0 2;
  text-align: center;
}}

{extra_css}
"""


class OmarchyRestoreApp(App):
    """The omarchy-restore TUI application."""

    SCREENS = {
        "welcome": WelcomeScreen,
        "preview": PreviewScreen,
        "diff": DiffScreen,
        "confirm": ConfirmScreen,
        "progress": ProgressScreen,
        "done": DoneScreen,
    }

    archive_path: str = ""
    target_path: str = ""
    diff_rows: list[DiffRow] = []
    omarchy_theme: object | None = None

    def on_mount(self) -> None:
        theme = load_active_theme()
        self.omarchy_theme = theme
        vars_block = "\n".join(
            f"  {k}: {v};" for k, v in theme.as_dict().items()
        )
        css_full = CSS_TEMPLATE.format(
            vars=vars_block,
            extra_css="",
        )
        self.styles = css_full
        self.push_screen("welcome")
