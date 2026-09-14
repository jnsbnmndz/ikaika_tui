"""The frame, header, footer and key hints every screen sits inside."""

from collections.abc import Sequence

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from company_tui.presentation.branding import (
    APP_NAME,
    APP_SIGNATURE,
    APP_TAGLINE,
    APP_VERSION,
    LOGO_MARK,
)

DEFAULT_WORKSPACE = "workspace ready"

HEADER_HEIGHT = 3
FOOTER_HEIGHT = 2

SIGNATURE_MIN_WIDTH = 78

FRAME_WIDTH = "100%"
FRAME_HEIGHT = "100%"


class AppFrame(Vertical):
    """Outer border every screen sits inside, so the app reads as one surface."""

    DEFAULT_CSS = f"""
    AppFrame {{
        width: {FRAME_WIDTH};
        height: {FRAME_HEIGHT};
        max-width: 100%;
        max-height: 100%;
        border: round $primary-lighten-2;
        background: $background;
        padding: 0;
    }}
    """

class AppHeader(Widget):
    DEFAULT_CSS = f"""
    AppHeader {{
        height: {HEADER_HEIGHT};
        border-bottom: solid $primary-lighten-1;
        padding: 0 2;
        layout: horizontal;
    }}

    /* Sized to the art, with the gap stated rather than left over as slack
       inside an oversized box — that slack is what pushed the mark off centre
       against the name beside it. */
    AppHeader .header--mark {{
        width: auto;
        height: 2;
        margin-right: 2;
        color: $accent;
    }}

    AppHeader #header-identity {{
        width: 1fr;
        height: 2;
    }}

    AppHeader #header-name {{
        height: 1;
        text-style: bold;
        color: $foreground;
    }}

    AppHeader #header-tagline {{
        height: 1;
        color: $text-muted;
    }}

    AppHeader #header-status {{
        width: auto;
        height: 1;
    }}

    AppHeader #header-version {{
        width: auto;
        color: $text-muted;
    }}

    AppHeader #header-dot {{
        width: auto;
        margin-left: 2;
        color: $success;
    }}

    AppHeader #header-workspace {{
        width: auto;
        margin-left: 1;
        color: $text-muted;
    }}

    /* Runs the user cannot currently see. Carried in the chrome rather than on
       one screen, because a run left going is exactly the thing that gets
       forgotten about the moment it is out of sight. */
    AppHeader #header-runs {{
        width: auto;
        height: 1;
        margin-left: 2;
        color: $accent;
    }}

    AppHeader #header-runs.-empty {{
        display: none;
    }}

    /* A window smaller than the interface was laid out for. Said rather than
       corrected: the app resizing the window it is drawn in fought the terminal
       over every rounded pixel, ten times a second — see
       `infrastructure/window_shape.py`. */
    AppHeader #header-window {{
        width: auto;
        height: 1;
        margin-left: 2;
        color: $warning;
    }}

    AppHeader #header-window.-empty {{
        display: none;
    }}

    /* A newer build, already downloaded, waiting to be run. $success rather than
       $warning: the window notice is something wrong that the user has to fix, and
       this is something ready that they may ignore. Two notices in one margin need
       to be tellable apart at a glance or the second one trains people to stop
       reading the first. */
    AppHeader #header-update {{
        width: auto;
        height: 1;
        margin-left: 2;
        color: $success;
        text-style: bold;
    }}

    AppHeader #header-update.-empty {{
        display: none;
    }}
    """

    RUNS_HINT = "Ctrl+B"
    UPDATE_HINT = "Ctrl+U"

    def __init__(self, workspace: str | None = None) -> None:
        super().__init__()
        self._workspace = workspace

    def compose(self) -> ComposeResult:
        yield Static(LOGO_MARK, classes="header--mark")
        with Vertical(id="header-identity"):
            yield Static(APP_NAME, id="header-name")
            yield Static(APP_TAGLINE, id="header-tagline")
        with Horizontal(id="header-status"):
            yield Static(APP_VERSION, id="header-version")
            yield Static("●", id="header-dot")
            yield Static(self._resolve_workspace(), id="header-workspace")
        runs = self._resolve_runs()
        yield Static(
            self._runs_text(runs), id="header-runs", classes="" if runs else "-empty"
        )
        window = self._resolve_window()
        yield Static(window, id="header-window", classes="" if window else "-empty")
        update = self._resolve_update()
        yield Static(
            self._update_text(update),
            id="header-update",
            classes="" if update else "-empty",
        )

    def show_runs(self, summary: str) -> None:
        """Say how many runs are going, or say nothing at all."""
        for badge in self.query("#header-runs"):
            badge.update(self._runs_text(summary))
            badge.set_class(not summary, "-empty")

    def show_window(self, notice: str) -> None:
        """Say the window is too small for the layout, or say nothing at all."""
        for badge in self.query("#header-window"):
            badge.update(notice)
            badge.set_class(not notice, "-empty")

    def show_update(self, notice: str) -> None:
        """Say a newer build is downloaded and how to run it, or say nothing."""
        for badge in self.query("#header-update"):
            badge.update(self._update_text(notice))
            badge.set_class(not notice, "-empty")

    @classmethod
    def _runs_text(cls, summary: str) -> str:
        return f"{summary} · {cls.RUNS_HINT}" if summary else ""

    @classmethod
    def _update_text(cls, notice: str) -> str:
        """The notice with the key that acts on it, the way the runs badge does."""
        return f"{notice} · {cls.UPDATE_HINT}" if notice else ""

    def _resolve_runs(self) -> str:
        return getattr(self.app, "runs_summary", "") or ""

    def _resolve_window(self) -> str:
        """Read at compose time as well as on change."""
        return getattr(self.app, "window_notice", "") or ""

    def _resolve_update(self) -> str:
        """Read at compose time as well as on change, exactly as the window notice."""
        return getattr(self.app, "update_notice", "") or ""

    def _resolve_workspace(self) -> str:
        if self._workspace:
            return self._workspace
        return getattr(self.app, "workspace_label", None) or DEFAULT_WORKSPACE


class HoverLight:
    """Lights a whole widget when the pointer is anywhere inside it."""

    def on_enter(self, event: events.Enter) -> None:
        self._sync_hover()

    def on_leave(self, event: events.Leave) -> None:
        self._sync_hover()

    def _sync_hover(self) -> None:
        over = self.app.mouse_over
        inside = over is self or (over is not None and self in over.ancestors)
        self.set_class(inside, "-hovered")


KEY_ALIASES = {"esc": "escape", "pgup": "pageup", "pgdn": "pagedown"}


def key_for(hint: str) -> str:
    """The key press a hint stands for, or `""` when it does not name one."""
    parts = [KEY_ALIASES.get(part, part) for part in hint.lower().split("+")]
    if not all(part.isascii() and part.isalnum() for part in parts):
        return ""
    return "+".join(parts)


class KeyHint(HoverLight, Widget):
    """A key, what it does, and a click that presses it."""

    DEFAULT_CSS = """
    KeyHint {
        width: auto;
        height: 1;
        margin-right: 3;
        layout: horizontal;
    }

    KeyHint .hint--key {
        width: auto;
        color: $foreground;
        text-style: bold;
    }

    KeyHint .hint--label {
        width: auto;
        margin-left: 1;
        color: $text-muted;
    }

    /* For hints that sit beside the thing they act on rather than along the
       bottom of the app, where whatever they are next to is the content. */
    KeyHint.-dim {
        margin-right: 2;
    }

    KeyHint.-dim .hint--key,
    KeyHint.-dim .hint--label {
        color: $text-disabled;
        text-style: none;
    }

    KeyHint.-pressable {
        pointer: pointer;
    }

    KeyHint.-pressable.-hovered .hint--key,
    KeyHint.-pressable.-hovered .hint--label {
        color: $accent;
        text-style: bold;
    }
    """

    def __init__(
        self,
        key: str,
        label: str,
        press: str = "",
        dim: bool = False,
        id: str | None = None,
    ) -> None:
        self._key = key
        self._label = label
        self._press = press or key_for(key)
        classes = ["-pressable"] if self._press else []
        if dim:
            classes.append("-dim")
        super().__init__(classes=" ".join(classes), id=id)

    @property
    def key(self) -> str:
        return self._key

    @property
    def pressable(self) -> bool:
        return self.has_class("-pressable")

    @pressable.setter
    def pressable(self, ready: bool) -> None:
        self.set_class(ready and bool(self._press), "-pressable")

    def compose(self) -> ComposeResult:
        yield Static(self._key, classes="hint--key")
        yield Static(self._label, classes="hint--label")

    def on_click(self, event: events.Click) -> None:
        if not self.pressable:
            return
        event.stop()
        self.app.simulate_key(self._press)


class AppFooter(Widget):
    DEFAULT_CSS = f"""
    AppFooter {{
        height: {FOOTER_HEIGHT};
        border-top: solid $primary-lighten-1;
        padding: 0 2;
        layout: horizontal;
    }}

    AppFooter #footer-hints {{
        width: 1fr;
        height: 1;
        overflow-x: hidden;
    }}

    AppFooter #footer-signature {{
        width: auto;
        height: 1;
        color: $text-disabled;
    }}

    AppFooter.-narrow #footer-signature {{
        display: none;
    }}
    """

    def __init__(self, hints: Sequence[tuple[str, str]] = ()) -> None:
        super().__init__()
        self._hints = tuple(hints)

    def compose(self) -> ComposeResult:
        with Horizontal(id="footer-hints"):
            for key, label in self._hints:
                yield KeyHint(key, label)
        yield Static(APP_SIGNATURE, id="footer-signature")

    def show_hints(self, hints: Sequence[tuple[str, str]]) -> None:
        """Replace the hints, for a screen where a key changes meaning."""
        self._hints = tuple(hints)
        container = self.query_one("#footer-hints", Horizontal)
        container.remove_children()
        container.mount_all([KeyHint(key, label) for key, label in self._hints])

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < SIGNATURE_MIN_WIDTH, "-narrow")


BUSY_FRAMES = ("◐", "◓", "◑", "◒")
"""The turning mark, from the same geometric block as everything else here."""

BUSY_INTERVAL = 0.12
"""Seconds a frame is held. Eight or so a second reads as turning rather than."""

class BusyLine(Widget):
    """What the app has to say for itself while a step is taking a while."""

    DEFAULT_CSS = """
    BusyLine {
        height: 1;
        margin: 1 2 0 2;
        color: $text-muted;
        display: none;
    }

    BusyLine.-busy {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = ""
        self._frame = 0
        self._turning: Timer | None = None

    def render(self) -> Content:
        glyph = BUSY_FRAMES[self._frame % len(BUSY_FRAMES)]
        return Content.assemble((f"{glyph}  ", "$secondary"), self._label)

    def show(self, label: str) -> None:
        """Say `label` and start turning, or stop and go away when it is empty."""
        self._label = label
        self.set_class(bool(label), "-busy")
        if label and self._turning is None:
            self._frame = 0
            self._turning = self.set_interval(BUSY_INTERVAL, self._turn)
        elif not label and self._turning is not None:
            self._turning.stop()
            self._turning = None
        self.refresh()

    def _turn(self) -> None:
        self._frame += 1
        self.refresh()
