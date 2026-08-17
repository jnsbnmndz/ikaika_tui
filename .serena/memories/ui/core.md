# TUI module
- Textual UI under `company_tui/presentation/`; `TuiConsole` drives screens and `PlainConsole` preserves scriptable `list`/`doctor` behavior.
- All selection menus reuse `CardMenuScreen` + `Card`; icons are terminal-safe line art from `presentation/icons.py`, hints from `presentation/hints.py`.
- Responsive menus use `CardMenuScreen._sync_density` / `_apply_density`: compact below 30 rows or when card width is insufficient.
- Cards have transparent backgrounds; focus alone uses the double accent border. Preserve theme tokens and shared `AppFrame` chrome.
- Never define widget/screen attribute `_context`; Textual reserves it internally.