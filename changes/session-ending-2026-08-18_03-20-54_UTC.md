# Change Summary -- unknown (measured from the last pushed commit) to 2026-08-18 03:20:54 UTC

**Session window:** Start: unknown (measured from the last pushed commit) | End: 2026-08-18 03:20:54 UTC
**Commit range:** 87584c8f..5113f00f

## Overview

One squashed commit reworking the toolbox around externally-declared build scripts, persistent run tabs, and window-size reporting: a stack's workflows and generators are now read from a cloned script repository (`ikaika.script.json`) rather than the toolbox source, run tabs survive restarts, and the window-resizing code was replaced with measurement-only reporting.

## Key Changes

**Script repositories (new subsystem)**
- `domain/script_config.py` (610 lines, new) ΓÇö parses a script repo's `ikaika.script.json`: `rules` (per-type argument constraints), `config` (sections that are either one action or a group, told apart by carrying `args`/`path`/`template`/`command-after-success`), `${...}` reference expansion against `${root}`, `${<action>.args.<flag>}`, `${<action>.path}`, `${<action>.filename}`, `${error}`. Unresolved references are left in place rather than blanked. Includes `ScriptAction`, `ScriptArgument` validation, `ScriptCatalogue`, `ScriptUpdate`, and the `components`/`workflows` filters.
- `templates/scripts.py` (558 lines, new) ΓÇö shared machinery so a pack declares only its `SCRIPTS` repo; `templates/react_native/` forwards `script_source`/`script_actions`/`run_script` to it.
- `capabilities/script_actions.py` (new) ΓÇö one walk (read store ΓåÆ version prompt ΓåÆ choose ΓåÆ form ΓåÆ panel ΓåÆ offer again) shared by Build and ScaffoldΓåÆComponents, parameterized by a filter.
- `capabilities/build.py` ΓÇö Build is now a menu of declared workflows, falling back to `TemplatePack.build()` when a stack declares none. `capabilities/scaffold.py` ΓÇö Components routes through the same walk, falling back to pack-shipped generators.
- Store semantics per the docs: cloned once to `scripts_root` (`~/.ikaika/scripts`), never pulled or checked out over; staleness read from fetched objects via `git show FETCH_HEAD:...`; "different" not "older"; three-way update menu (re-clone / keep / stop asking) shown *before* the workflow menu.
- Overwrite is waived only by an action's own declared boolean `overwrite` flag; declared booleans always render as one of two words.

**Session persistence**
- `domain/session_memory.py` + `infrastructure/session_file.py` (new) ΓÇö tabs persisted as JSON under the user's home, keyed by the startup directory (wired in `bootstrap.py`). Restored tabs are idle: no task, output wrapped in `HISTORY_OPENED`/`HISTORY_CLOSED`. Written on run end, rename, close, and quit ΓÇö never per line.
- `presentation/session.py`, `session_tabs.py`, `tui_console.py` ΓÇö `to_memory`/`replay`, `_teach` handing the walking workflow to idle tabs, `SessionRegistry.restore` clearing `foreground`.

**Window shape**
- `infrastructure/window_shape.py` (new, 210 lines) ΓÇö measure-only. The prior resize-to-floor/ratio loop is removed; docs record it pegging CPU/GPU until a display-driver reset (foreign-process `SetWindowPos` blocking the event loop, repaint per correction, non-convergence from cell snapping + DPI rounding). `CONSOLE_WINDOW_CLASS` checked by name, falling back to the foreground window because `GetConsoleWindow` returns a visible 0├ù0 pseudo-console under Windows Terminal.
- `TuiConsole` polls at `WINDOW_POLL_INTERVAL` and writes `WINDOW_NOTICE` to the header only when the measurement changed. `terminal_window.py` emits no sizing sequence.

**Run panel / UI**
- `run_screen.py` (+681 lines) ΓÇö `SelectableLog` replaces `RichLog`: `render_line` stamps per-cell offsets and paints the selection, `get_selection` reads text back off the strips; highlight applied as `post_style`, background only. COPY (whole transcript from `RunSession.transcript`) and CLEAR (clears the session, keeps the `$` prompt) beside Send, disabled when empty.
- `chrome.py` ΓÇö `BusyLine` + `Ui.working(label, work)` for panel-less steps, shown only after `BUSY_DELAY`; cancel propagates to the work.
- `screens.py`/`branding.py` ΓÇö `ConfirmScreen` buttons stay outlines with focus doubling the border (`!important` on border/background/`text-style`, `background-tint: 0%`); `FieldToggle` is box-only with a separate label, `TOGGLE_ON` interpolated rather than a theme variable.

**Config & ports**
- `domain/config.py` ΓÇö `scripts_root`, `scripts` (separate from `templates`), `script_checks`; `ConfigPort` gains `script_source`, `scripts_root`, `script_check`.
- `domain/ports.py` ΓÇö `run`/`stream`/`capture` take `cwd`; `FileSystemPort.remove_file` added for undoing a staged template when its follow-up command fails.
- `capabilities/settings.py` ΓÇö per-stack rows for script URL/ref, an INFO row describing the store, an install/re-clone toggle (fetch happens *after* the save), and a watch toggle. Building the form fetches nothing.
- `domain/template_pack.py`, `presentation/ui.py`, `plain_console.py`, `icons.py`, `hints.py`, `card.py` updated to match.

**Docs** ΓÇö `CLAUDE.md` gains "Build scripts" and "Window shape" sections; `AGENT.md` records the `SelectableLog` selection mechanics, the resize post-mortem, and two Textual specificity traps (`Button.-flat` outranking `Screen Button`; `$button-focus-text-style` being `bold reverse`).

## Risks / Follow-ups

- **Everything landed as one squashed commit** across 34 files (+4073/ΓêÆ217), so nothing here is individually revertable or bisectable.
- **No test files appear in the diff.** `CLAUDE.md`/`AGENT.md` reference `tests/test_window_shape.py`, `tests/test_glyphs.py`, and a test asserting `terminal_window.py` has no resize function, but no test changes are in this commit ΓÇö the window-shape and script-config work is undertested relative to its size by the repo's own definition of done. Likewise `tools/window_trace.py` is described in docs but not present in the diff.
- **Window measurement cannot be covered by `python -m unittest`** (a pilot has no window), and the docs note it is Windows-only via `ctypes` ΓÇö behavior on other hosts/platforms rests on the `os.name` and `is_headless` guards.
- **Script repositories are executed from the toolbox**: `command-after-success` runs arbitrary commands with the script repo as cwd. The pinning is per-stack config (`[scripts.<pack>] ref`), and a store already present is never verified against the remote ref again beyond the courtesy version check.
- **Version staleness is string-inequality only** ΓÇö deliberately, per the docs, but it means a user deliberately sitting behind gets prompted until they choose "stop asking."
- The truncated portion of the diff (past 100k chars) was not reviewable here, so `templates/scripts.py`, the later half of `script_config.py`, and much of `run_screen.py`/`tui_console.py` are summarized from the visible portions and the documentation added alongside them.
- `.gitignore` now ends without a trailing newline after the added `test.*` / `test/` entries.