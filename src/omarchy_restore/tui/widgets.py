"""Custom widgets for omarchy-restore."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from omarchy_restore.omarchy import Category


class Wordmark(Static):
    """The app wordmark shown on the Welcome screen."""

    DEFAULT_CSS = """
    Wordmark {
        height: 1;
        padding: 0 0 0 0;
        text-style: bold;
    }
    """

    def render(self) -> str:
        return "█ █ omarchy-restore"


class CategoryChip(Static):
    """A single category chip showing the one-letter abbreviation."""

    category: reactive[Category | None] = reactive(None)

    def render(self) -> str:
        if self.category is None:
            return ""
        c = self.category
        return f"[{c.value}]"

    def watch_category(self, cat: Category | None) -> None:
        if cat is None:
            self.remove_class("cat-chip-active")
        else:
            self.add_class("cat-chip-active")


class StatusIndicator(Static):
    """A status indicator showing the 4-char token (e.g. ``+ NEW``)."""

    status: reactive[str] = reactive("")

    def render(self) -> str:
        return self.status
