# macOS Build, Settings Fixes & Advanced Defaults

> **Scope:** Planning and engineering specification for (1) fixing defects found in the current settings and form pipeline, (2) promoting all Advanced/experimental features to enabled-by-default, and (3) building, packaging, signing, self-updating, and releasing DTI natively on macOS.
>
> **Status:** Draft plan — no source files modified yet. Follow `CLAUDE.md`, `docs/decisions/`, and `docs/pitfalls.md` when executing each phase.

---

## Table of Contents

1. [Plan](#1-plan)
2. [Findings](#2-findings)
   - [2.1 Bugs in Current Settings & Forms](#21-bugs-in-current-settings--forms)
   - [2.2 Promoting All Advanced Settings to Default-On](#22-promoting-all-advanced-settings-to-default-on)
   - [2.3 macOS Codebase & Local Environment Findings](#23-macos-codebase--local-environment-findings)
3. [Implementation](#3-implementation)
   - [3.1 Phase 1 — Settings Bug Fixes & Advanced Defaults](#31-phase-1--settings-bug-fixes--advanced-defaults)
   - [3.2 Phase 2 — Cross-Platform Runtime & macOS Parity](#32-phase-2--cross-platform-runtime--macos-parity)
   - [3.3 Phase 3 — macOS Build, Packaging & CI Pipeline](#33-phase-3--macos-build-packaging--ci-pipeline)
   - [3.4 Phase 4 — Tests, Decisions & Copy Sync](#34-phase-4--tests-decisions--copy-sync)
4. [Build Processes (macOS Local & CI)](#4-build-processes-macos-local--ci)
   - [4.1 Prerequisites & Clean Environment Setup](#41-prerequisites--clean-environment-setup)
   - [4.2 Local Build Pipeline (`./script.sh`)](#42-local-build-pipeline-scriptsh)
   - [4.3 Install Layout & Release/Debug Isolation](#43-install-layout--releasedebug-isolation)
   - [4.4 Packaging Formats (`.pkg` Primary + `.tar.gz` Portable)](#44-packaging-formats-pkg-primary--targz-portable)
   - [4.5 Code Signing & Notarization](#45-code-signing--notarization)
   - [4.6 In-App Self-Update Handover on macOS](#46-in-app-self-update-handover-on-macos)
   - [4.7 Benchmarking & Release Workflow (GitHub Actions)](#47-benchmarking--release-workflow-github-actions)
   - [4.8 Pre-Release Verification Checklist](#48-pre-release-verification-checklist)
5. [Open Questions & Custom Bug Notes](#5-open-questions--custom-bug-notes)

---

## 1. Plan

### Objectives

1. **Eliminate silent data loss and form defects in Settings, Advanced, App Setup, and Builder** before cutting a macOS build, so every settings surface (`Settings`, `Advanced`, `App Setup`, `Builder`, and `Scripts` "Stop asking") preserves all fields and behaves identically.
2. **Promote all Advanced experimental features to enabled-by-default**:
   - `interactive_lists = true`
   - `timed_prompts = true`
   - `browser_view = true`
   - Plus keep all `[updates]` defaults coherent (`repository = "jnsbnmndz/ikaika_tui"`, `api_base = "https://api.github.com"`, `channel = "official"`, `check_on_launch = true`, platform-appropriate `asset_pattern`), while ensuring opting **out** (`= false` / `""`) persists cleanly across save/reload/export/import.
3. **Achieve first-class macOS build & runtime parity** with Windows while respecting every invariant in `CLAUDE.md`:
   - Zero new runtime third-party dependencies (stay on `textual>=8.2,<9` + stdlib + native macOS tools).
   - One command entry point shared by local dev machines and GitHub Actions (`./script.sh` alongside Windows' `.\script.ps1`).
   - Per-user installation with **no `sudo`/admin prompt**, clean release (`dti`) vs debug (`dti-debug`) isolation, safe PATH registration, Apple Silicon signing (ad-hoc for local/debug, Developer ID + notarization for official releases), and silent self-update handover.

### Phased Roadmap

| Phase | Deliverable | Gate Criteria |
|---|---|---|
| **Phase 0** | Repo hygiene: clean macOS `.venv`, reconcile `uv.lock` vs `VERSION`/`pyproject.toml`, add `.gitattributes` for LF/CRLF stability | `python -m company_tui check` and `ruff check` pass on macOS |
| **Phase 1** | Fix all Settings/Advanced/Builder/RunScreen/Session bugs + flip Advanced experimental flags to default `True` with sparse `= false` persistence | New `tests/test_settings_capability.py` + `tests/test_advanced_capability.py` pass; updated gate/browser/layout tests pass |
| **Phase 2** | Cross-platform runtime parity: platform-aware update asset pattern, `MacOSHandover`, POSIX `termios` terminal restore, macOS clipboard fallback (`pbcopy`), cross-platform `build_kind` & command preview | All unit tests + new macOS handover/update/terminal tests pass on both macOS and Windows |
| **Phase 3** | macOS build & packaging scripts (`./script.sh`, `scripts/mac/*`), `.pkg` + `.tar.gz` artifacts, signing/notarization, macOS benchmark, GitHub Actions `macos-latest` check & release jobs | Frozen `dti` starts, prints correct `VERSION`, runs `list`/`doctor`/TUI, installs via `.pkg` without `sudo`, updates cleanly |
| **Phase 4** | Update `docs/decisions/` (new/amended ADRs), `docs/pitfalls.md`, `CLAUDE.md`, `README.md`, `presentation/hints.py`, on-screen copy, and `graphify update .` | Full gate passes on macOS + Windows CI |

---

## 2. Findings

All findings below were verified directly against the current repository source and this Apple Silicon macOS host.

### 2.1 Bugs in Current Settings & Forms

| ID | Severity | Location | Summary |
|---|---|---|---|
| **S-01** | Critical | `company_tui/capabilities/settings.py:225-246` | **`SettingsCapability._save()` wipes `updates`, `layout`, and all 3 `experimental` flags.** `_save()` instantiates a brand-new `Settings(...)` without reading `current = self._config.settings()`. Every save in `[05] Settings` silently resets custom update sources, turns off `interactive_lists`/`timed_prompts`/`browser_view`, and deletes every Builder theme, window size, and menu customization. |
| **S-02** | Critical | `company_tui/capabilities/settings.py:280-299` | **`SettingsCapability._sources()` and `_checks()` drop stack entries not registered as active packs.** Both helpers only iterate `self._pack_registry.all()`. Any `[templates.<key>]`, `[scripts.<key>]`, or `script_checks` entry added via Browser Builder ("Add pack"/"Add repository") or manually in `dti.toml` is silently deleted on the next Settings save. |
| **S-03** | Critical | `company_tui/capabilities/advanced.py:182-211` | **`AdvancedCapability._save()` wipes `layout` (and `check_on_launch`).** `_save()` manually copies fields from `current` into `Settings(...)` instead of `dataclasses.replace(current, ...)` and omits `layout=current.layout`. It also constructs `UpdateSource(...)` without `check_on_launch=current.updates.check_on_launch`, resetting `check_on_launch = false` back to `True`. |
| **S-04** | Critical | `company_tui/presentation/session.py:230-233`, `company_tui/capabilities/advanced.py:101-114,176-198` | **`RunSession.load()` blanks all `OptionKind.CHOICE` values, silently resetting `Advanced` Channel to `official`.** To match script-form parity (`tests/test_form_parity.py`), `session.load()` forces `self.values[option.key] = ""` for every `CHOICE` option. In `Advanced`, if `[updates] channel` is `"prerelease"` or `"any"` and the user saves without manually re-picking the Channel dropdown, `_channel_named("")` falls back to `CHANNEL_OFFICIAL` and silently overwrites the channel. The same blanking affects `Save to` (`scope`) across `Settings`, `Advanced`, `App Setup`, and `Builder`. |
| **S-05** | High | `company_tui/presentation/run_screen.py:879-886` | **`FieldToggle` renders `bool(option.default)` instead of `self._session.values.get(option.key, option.default)`.** Every other control reads from `self._session.values`, but `BOOLEAN` ignores it. Restoring a tab from `sessions.json`, switching tabs (`_swap_form`), or reloading a session with saved values visually reverts checkboxes to `option.default` while `session.values` holds the edited value — causing a silent UI-vs-submitted-value mismatch. |
| **S-06** | High | `company_tui/presentation/tui_console.py:714-723,806-809` | **"Run again" in Settings/Advanced/App Setup skips reloading fresh options and leaves one-shot action toggles armed.** `close_run_panel()` resets the session while keeping `session.panel_open = True`, so the next loop iteration's `open_run_panel()` skips `session.load(...)`. Consequence: `Reading now`, `Would ask`, and `<Stack> store` stay stale after saving; `Reset these to defaults` (Advanced), `Install / Re-clone scripts` (Settings), and `Overwrite the file` (App Setup) remain checked on re-run and accidentally fire a second time. |
| **S-07** | High | `company_tui/capabilities/advanced.py:166-211` | **"Reset these to defaults" (`RESET_KEY`) is broken and contradicts its help text.** Help says *"Clears the repository and puts everything else back"*, but `_save()` sets `source = UpdateSource()` (whose `repository` is `DEFAULT_REPOSITORY`, not `""`) and **never resets** `interactive_lists`, `timed_prompts`, or `browser_view` — it keeps reading the form's current checkbox values instead. |
| **S-08** | High | `company_tui/infrastructure/config.py:70-85`, `company_tui/domain/settings_document.py:59-64,207-238`, `company_tui/capabilities/advanced.py`, `company_tui/infrastructure/builder_page.py` | **`[updates] check_on_launch` is read by `FileConfig` (`config.py:247`) and documented in `README.md:469`, but dropped everywhere else.** `render()` never writes `check_on_launch = false`, `write_document()`/`read_document()` omit it, and neither `Advanced` nor `Builder` exposes a toggle for it. Any save from any UI deletes a user's `check_on_launch = false`. |
| **S-09** | High | `company_tui/capabilities/advanced.py:74`, `company_tui/capabilities/builder.py:89`, `company_tui/templates/scripts.py:141-145` | **Scope shadowing causes saved changes to be silently ignored.** Because `FileConfig` uses first-file-wins (`driven` -> `project` -> `user`, never merged), defaulting `Save to` to `user` in `Advanced` and `Builder` while a `project` (or `driven`) `dti.toml` is active writes to `~/.dti/dti.toml`, which is immediately shadowed by the active project file (including this repo's own `./dti.toml`). Additionally, `templates/scripts.py:_active_scope()` only checks `PROJECT` vs `USER` and ignores `ConfigScope.DRIVEN`, so "Stop asking" in a driven project writes to `user` and keeps re-prompting. |
| **S-10** | Medium | `company_tui/bootstrap.py:58,125,145` | **Three separate `FileConfig()` instances cause stale update config.** `_build_capability_registry()`, `_build_update_watch()`, and `create_tui_console()` each construct their own `FileConfig()`. Saving in Settings/Advanced/Builder invalidates only instance #1; `UpdateWatch` (used by `Ctrl+U`) retains its cached `_settings` until restart and never receives `config.follow(root)`. |
| **S-11** | Medium | `company_tui/domain/settings_document.py:99-100,207-238`, `company_tui/infrastructure/config.py:102,111`, `company_tui/capabilities/builder.py:123`, `company_tui/infrastructure/builder.py:281`, `company_tui/infrastructure/builder_page.py:325-331,349-352` | **Validation & Builder drift bugs:** (a) `read_document()` does not validate `bundle_prefix` (`BUNDLE_PREFIX_SHAPE`) or `UpdateSource.problem`, letting Builder/App Setup write invalid values that `Settings`/`Advanced` reject; (b) `render()` writes unquoted `[templates.<key>]` / `[scripts.<key>]` headers — a key with spaces or dots from Builder's "Add pack" produces invalid TOML that breaks `tomllib.load`; (c) `BuilderCapability._manifest()` calls `naming.project_root()` instead of the `config.follow()` driven root; (d) non-numeric `Content-Length` raises uncaught `ValueError` in `builder.py:281`; (e) `builder_page.py` ignores `0` in `parseInt(...) \|\| prev` and does not sync normalized `body.document` on clean POSTs. |
| **S-12** | Medium | `company_tui/presentation/path_screen.py:22-32,163-172` | **File picker usability gaps in settings forms.** `PathScreen` handles `DirectoryTree.DirectorySelected` but not `DirectoryTree.FileSelected` (pressing Enter on a file in App Setup or local installer picker does not select it), and `DirectoryOnlyTree.filter_paths()` unconditionally hides all dot-prefixed entries (`.dti`, `.dti_configs`), making `~/.dti/` unreachable via Browse. |

---

### 2.2 Promoting All Advanced Settings to Default-On

Currently, the three feature switches in `Advanced` are **experimental and off by default**:

- `interactive_lists` (`domain/config.py:64,115`)
- `timed_prompts` (`domain/config.py:67,126`)
- `browser_view` (`domain/config.py:70,136`)

Flipping them to `True` by default is **not** a three-line edit — doing only that would introduce a silent persistence regression because serialization and reading currently assume `False` is the omitted default:

1. **TOML Reader (`infrastructure/config.py:258-265`)** currently checks `is True` (absent -> `False`). Must invert to `.get(key, True) is not False` (absent -> `True`, explicit `false` -> `False`), matching `script_check()` and `check_on_launch`.
2. **TOML Writer (`infrastructure/config.py:86-94`)** currently emits `key = true` when `True` and omits `False`. Must invert to **omit when `True` (default)** and **explicitly emit `key = false` when `False`**, otherwise turning a feature OFF in `Advanced` or `Builder` would silently flip back to `True` on reload.
   - Note on TOML section naming: Keep `[experimental]` readable AND writable for full backward compatibility with existing `dti.toml` files and JSON schema v1 documents (`"experimental": {...}`). Optionally document or alias it cleanly without breaking existing files or `tests/test_settings_document.py`.
3. **Domain & Port Defaults (`domain/config.py:64-75, 107-136`)**:
   - `Settings.interactive_lists: bool = True`
   - `Settings.timed_prompts: bool = True`
   - `Settings.browser_view: bool = True`
   - `ConfigPort.interactive_lists()`, `timed_prompts()`, `browser_view()` concrete fallbacks return `True`.
   - Safety invariant still holds: every one of these features is **still two-key gated** — a command's `dti.script.json` must explicitly declare `"interactive": true` or `"view": "browser"`, and a listing must explicitly send `timeout` + `default`, so non-interactive scripts continue to run byte-for-byte unchanged (`stdin=DEVNULL`, no `DTI_INTERACTIVE`).
4. **Browser Builder (`infrastructure/builder_page.py:116-120, 275-281, 583-595`)**:
   - Update tab hint copy from *"Off by default..."* to *"On by default; untick to fall back to plain terminal output. Commands still opt in via their manifest."*
   - Keep `box.checked = doc.experimental[key] !== false` (defensive against partial docs).
5. **TUI Copy & Docs (`CLAUDE.md` rule: behaviour and its description change together)**:
   - `company_tui/capabilities/advanced.py:129-165, 216-227`: remove `(experimental)` tags / "off by default" phrasing, add `check_on_launch` toggle, clarify `RESET_KEY` restores all Advanced settings (update source + feature flags) to built-in defaults.
   - `README.md`, `CLAUDE.md`, `docs/decisions/0005`, `docs/decisions/0006`: amend records to reflect graduation from opt-in experimental to default-on.
6. **Existing Tests Asserting Default-Off**:
   - `tests/test_interactive_gate.py:124-125, 148-153, 162-163, 186-198`
   - `tests/test_browser.py:291-297, 320-322`
   - `tests/test_layout.py:562-578`
   - Must be updated to assert default-`True`, explicit `= false` persistence on opt-out, and absence of `[experimental]` lines in `render(Settings())` when untouched.

---

### 2.3 macOS Codebase & Local Environment Findings

#### A. Local Apple Silicon Host Audit (`Darwin arm64`)

| Check | Observed on This Machine | Impact & Action Needed |
|---|---|---|
| Architecture & OS | Apple Silicon `arm64`, macOS 27.2.1 (`Darwin 27.2.0`) | Native `arm64` builds; Mach-O binaries **must** be signed (at least ad-hoc `codesign -s -`) or macOS kills them with `SIGKILL`. |
| Existing `.venv/` | Contains **Windows** layout (`.venv/Scripts`, `.venv/Lib`, no `.venv/bin`) | Cannot execute on macOS; delete and recreate a macOS `.venv`. |
| System Python | `/usr/bin/python3` is **3.9.6** | Below `requires-python = ">=3.11"` in `pyproject.toml`. Must never fall back to `/usr/bin/python3`. |
| Homebrew Python | `/opt/homebrew/bin/python3` is **3.15.2** | Bleeding-edge; verify `pyinstaller` + `textual` wheel/hook support, and prefer pinning **CPython 3.12 or 3.13** via `uv` or `brew install python@3.13` for release builds. |
| `uv` & `pyinstaller` | Not currently on PATH | Install `uv` (`brew install uv`) so `.venv` & pinned Python versions work deterministically like Windows. |
| Apple Toolchain | `codesign`, `hdiutil`, `pkgbuild`, `productbuild`, `xcrun`, `xcrun notarytool 1.1.4`, `brew`, `pwsh 7.6.5` all present | Full native macOS packaging and notarization toolchain is available without third-party installers (no NSIS equivalent needed). |
| `uv.lock` vs `VERSION` | `VERSION` & `pyproject.toml` say `0.4.0+31`; `uv.lock` says `0.4.1+34` (and `README.md` benchmark says `0.4.1+34`) | `check-all`'s version-consistency gate will **FAIL** until `uv.lock` is reconciled with `VERSION`. |
| Git line endings | 11 files show full-file CRLF/LF diffs (`git diff -w` is empty) | Add `.gitattributes` enforcing LF for text files (`.py`, `.sh`, `.md`, `.toml`, `.yml`, `.json`) to stop cross-OS churn. |
| Runtime dependencies (`uv.lock`) | `textual`, `rich`, `markdown-it-py`, `mdit-py-plugins`, `mdurl`, `linkify-it-py`, `platformdirs`, `pygments`, `typing-extensions` are **100% pure Python (`py3-none-any`)**; `ruff` (dev-only) already ships `macosx_11_0_arm64` & `macosx_10_12_x86_64` wheels | Zero third-party C extension blockers when freezing with PyInstaller on macOS! |

#### B. Windows-Only / Platform-Specific Code Paths in `company_tui/`

| Module | Current Windows Assumption | macOS Requirement |
|---|---|---|
| `company_tui/domain/updates.py:18` | `DEFAULT_ASSET_PATTERN = "*-setup*.exe"` | Platform-aware default: Windows `*-setup*.exe`, macOS `*-macos-arm64*.pkg` / `*-macos-x86_64*.pkg` (or `*-macos-universal*.pkg` if universal). Treat `""` or platform-default carefully on cross-OS JSON import so importing a Windows config onto macOS doesn't lock macOS to `.exe`. |
| `company_tui/domain/updates.py:43-48` | `build_kind()` uses `PurePath(command).stem` | On POSIX, `\` is not a path separator; normalize `command.replace("\\", "/")` before taking `.stem` so cross-platform tests and paths behave identically. |
| `company_tui/capabilities/updates.py:39,273,300` | Rejects any local file whose suffix is not `.exe`; fallback filename `*-setup.exe` | Accept platform-valid installer suffixes (`.pkg` / `.tar.gz` on macOS, `.exe` on Windows) and platform-appropriate wording/fallback names. |
| `company_tui/application/updates.py:27,163,186` | `SWEEPABLE = frozenset({".exe", ".part"})`; fallback `update-setup.exe` | Expand `SWEEPABLE` to include macOS installer artifacts (`".pkg"`, `".dmg"`, `".gz"`, `".tgz"` — specifically safe suffixes inside the `updates` dir) while preserving the `CACHE_DIRECTORY == "updates"` safety guard (`docs/pitfalls.md 6.3`). |
| `company_tui/infrastructure/handover.py` & `bootstrap.py:129` | `WindowsHandover` returns `"handing over to an installer is Windows-only"` when `os.name != "nt"`; `bootstrap.py` hardcodes `WindowsHandover()` | Implement `MacOSHandover(HandoverPort)` using a detached POSIX `sh` waiter script in `$TMPDIR` (`start_new_session=True`, `kill -0 $WAIT_PID` poll loop, silent per-user `installer -pkg ... -target CurrentUserHomeDirectory` or `.tar.gz` atomic swap, log kept on failure & deleted on success, relaunch if frozen). Select via `default_handover()` factory in `handover.py`/`bootstrap.py`. |
| `company_tui/infrastructure/terminal_window.py` | `console_modes()` / `restore_terminal_interaction()` are no-ops on POSIX; `release_terminal()` writes ANSI reset sequences | Add POSIX `termios.tcgetattr`/`tcsetattr` save & restore in `console_modes()` / `release_terminal()` on `os.name == "posix"` so a `KeyboardInterrupt` or abnormal crash never strands macOS Terminal/iTerm2 in raw/no-echo mode. |
| `company_tui/infrastructure/window_shape.py` | Returns `None`/`False` when `os.name != "nt"` (graceful no-op — does not crash) | Keep graceful no-op on macOS by default (terminal emulators on macOS — Terminal.app, iTerm2, Ghostty, Warp, Kitty, Alacritty — manage window geometry differently and have no single `user32` API). Optionally add a lightweight cell-grid cramped check (`self.size.width < MIN_COLS`) for the header warning badge, and note in Builder's Window tab that pixel sizing applies on Windows. |
| `company_tui/presentation/run_screen.py:1403-1409` | `_copy_terminal()` calls `self.app.copy_to_clipboard()` (OSC 52) | Apple's built-in **Terminal.app ignores OSC 52** clipboard writes. On `sys.platform == "darwin"`, also pipe to `/usr/bin/pbcopy` (with `stdin=PIPE`, `shell=False`, timeout) as a reliable native fallback. |
| `company_tui/presentation/run_screen.py:195-203` & `session_tabs.py` | Tab switching bound to `ctrl+pageup`/`ctrl+pagedown`; rename bound to `f2` | On MacBooks without dedicated PageUp/PageDown keys, `Ctrl+Fn+Up/Down` conflicts with macOS Mission Control. Keep existing bindings and add macOS-friendly secondary bindings (e.g., `ctrl+left`/`ctrl+right` or `[`/`]` where safe, or `alt+left`/`alt+right` when not in an Input) so MacBook users can switch tabs without mouse or Mission Control conflicts. |
| `company_tui/domain/script_config.py:428` | `command_preview()` hardcodes `.\script.ps1` | Use `./script.sh` or `./script.ps1` when `os.name != "nt"` (or detect from the action's actual `after_success[0]` command!). |
| `scripts/build-app.ps1:106` & all `scripts/*.ps1` | Hardcodes `;` in PyInstaller `--add-data`, `.venv\Scripts\python.exe`, `dti.exe`, `makensis.exe`, `signtool.exe`, `winget`, `choco` | macOS PyInstaller requires `:` (`VERSION:.`) in `--add-data`; build/check/package/sign/benchmark scripts need native macOS implementations under `scripts/mac/` + `./script.sh`. |

---

## 3. Implementation

### 3.1 Phase 1 — Settings Bug Fixes & Advanced Defaults

#### 1. `company_tui/domain/config.py`
- Flip defaults on `Settings`:
  ```python
  interactive_lists: bool = True
  timed_prompts: bool = True
  browser_view: bool = True
  ```
- Flip concrete fallback methods on `ConfigPort` (`interactive_lists()`, `timed_prompts()`, `browser_view()`) to return `True` and update docstrings to state they are enabled by default and can be opted out of.
- Add `BUNDLE_PREFIX_SHAPE` (move from `capabilities/settings.py` into `domain/config.py` as a shared validation constant/helper `is_bundle_prefix(value: str) -> bool`) so `SettingsCapability` and `settings_document.py` share one single source of truth.
- Add `driven_root(self) -> Path | None` (default `None`) on `ConfigPort` so `BuilderCapability` and `templates/scripts.py` can query the currently followed project root cleanly through the port.

#### 2. `company_tui/infrastructure/config.py`
- **Invert sparse experimental rendering in `render()`**:
  ```python
  experimental = []
  if not settings.interactive_lists:
      experimental.append("interactive_lists = false")
  if not settings.timed_prompts:
      experimental.append("timed_prompts = false")
  if not settings.browser_view:
      experimental.append("browser_view = false")
  if experimental:
      lines += ["", f"[{EXPERIMENTAL_SECTION}]", *experimental]
  ```
- **Invert reading in `FileConfig`**:
  ```python
  def interactive_lists(self) -> bool:
      return self._section(EXPERIMENTAL_SECTION).get("interactive_lists", True) is not False

  def timed_prompts(self) -> bool:
      return self._section(EXPERIMENTAL_SECTION).get("timed_prompts", True) is not False

  def browser_view(self) -> bool:
      return self._section(EXPERIMENTAL_SECTION).get("browser_view", True) is not False
  ```
- **Persist `check_on_launch = false` in `render()`**:
  ```python
  if not updates.check_on_launch:
      update_lines.append("check_on_launch = false")
  ```
- **Quote unsafe TOML table keys** in `render()` for `[templates.<key>]` and `[scripts.<key>]`:
  - Helper `_toml_key(key: str) -> str`: return bare `key` if `re.fullmatch(r"[A-Za-z0-9_-]+", key)`, else `quote(key)`.
- **Implement `driven_root()` on `FileConfig`**: return `self._driven.parent if self._driven is not None else None`.

#### 3. `company_tui/domain/settings_document.py`
- Include `"check_on_launch": settings.updates.check_on_launch` in `write_document()["updates"]`.
- Read `check_on_launch` in `_updates()` (validating `isinstance(..., bool)`, reporting problem if non-bool, keeping `fallback.check_on_launch` when absent).
- Validate `bundle_prefix` using shared `is_bundle_prefix()` in `read_document()`; if invalid, keep `current.bundle_prefix` and append a clear entry to `problems`.
- Validate constructed `UpdateSource` via `source.problem` when `source.configured` in `_updates()`; if invalid, keep `fallback` and report `source.problem` in `problems`.

#### 4. `company_tui/domain/options.py` & `company_tui/presentation/session.py` & `company_tui/presentation/run_screen.py`
- **Fix Bug S-04 without breaking script-form parity (`tests/test_form_parity.py`)**:
  - Add `bind_default: bool = False` (or `allow_blank: bool = True`) to `Option` (`domain/options.py`):
    - Script arguments from `action_options()` keep `allow_blank=True` (so untouched dropdowns still bind `""` and omit `-Branch` in `command_preview`, preserving 100% of `tests/test_form_parity.py`).
    - Settings / Advanced / App Setup / Builder `CHOICE` options set `allow_blank=False` (a settings choice like `Save to`, `Channel`, or `What to do` ALWAYS has a concrete selected value).
  - In `RunSession.load()`: only blank `CHOICE` when `option.allow_blank` is `True`.
  - In `RunScreen._form_widgets()`: pass `allow_blank=option.allow_blank` to `Select(...)` and pre-select `stored` (falling back to `option.default` when `not option.allow_blank`).
- **Fix Bug S-05 (`FieldToggle` state sync)**:
  - In `run_screen.py:882`, change:
    ```python
    FieldToggle(
        value=bool(self._session.values.get(option.key, option.default)),
        id=widget_id,
    )
    ```
- **Fix Bug S-06 ("Run again" stale form & sticky one-shot checkboxes)**:
  - Add an option or reload mechanism when `open_run_panel()` is called after `close_run_panel()` returns `True`:
    - When `session.reset()` runs (or when `open_run_panel()` sees `session.options != tuple(options)` or a fresh loop entry after `reset()`), re-apply `session.load(...)` with the freshly computed `options` and swap/re-render the form widgets on `RunScreen` (updating `INFO` rows, resetting transient checkboxes like `reset`, `fetch_*`, `overwrite` to `False`, while preserving non-transient answers where appropriate or re-reading fresh persisted settings!).
    - Specifically for settings capabilities (`Settings`, `Advanced`, `App Setup`), re-reading `self._config.settings()` and refreshing the form on `Run again` guarantees the form ALWAYS reflects what was just written to disk.

#### 5. `company_tui/capabilities/settings.py`
- **Fix Bugs S-01 & S-02**:
  - Read `current = self._config.settings()` at the start of `_save()`.
  - Merge edited pack entries over `dict(current.templates)`, `dict(current.scripts)`, and `dict(current.script_checks)` so non-registered pack keys survive untouched.
  - Build the saved settings with `dataclasses.replace(current, workspace_root=..., bundle_prefix=..., templates=..., scripts_root=..., scripts=..., script_checks=...)` — preserving `updates`, `layout`, `interactive_lists`, `timed_prompts`, `browser_view`.
- **Fix Bug S-09 (active scope default)**:
  - Default `SCOPE_KEY` to whichever scope is currently active (`DRIVEN` if active == driven, `PROJECT` if active == project, `USER` if active == user, else `PROJECT`), and warn in the terminal output if saving to a lower-precedence scope while a higher-precedence file exists and will shadow it!

#### 6. `company_tui/capabilities/advanced.py`
- **Fix Bugs S-03, S-04, S-07, S-08, S-09**:
  - Add `CHECK_ON_LAUNCH_KEY = "check_on_launch"` boolean option (`default=source.check_on_launch`).
  - Default `SCOPE_KEY` to the active scope (falling back to `ConfigScope.USER` only when no higher-precedence file exists), with `allow_blank=False` on both `SCOPE_KEY` and `CHANNEL_KEY`.
  - In `_save()`:
    - When `values.get(RESET_KEY)` is truthy: reset `updates = UpdateSource()`, `interactive_lists = True`, `timed_prompts = True`, `browser_view = True` (all built-in defaults) and update `RESET_KEY` help copy to accurately state: *"Restores the update source and feature toggles to built-in defaults."*
    - Otherwise: preserve `check_on_launch=bool(values.get(CHECK_ON_LAUNCH_KEY, current.updates.check_on_launch))`, and use `self._channel_named(str(values.get(CHANNEL_KEY, "")), fallback=current.updates.channel)` so a blank value never silently downgrades `channel`.
    - Construct via `dataclasses.replace(current, updates=source, interactive_lists=..., timed_prompts=..., browser_view=...)` — **preserving `current.layout` and every other field**.
  - Update option labels/help text to remove `(experimental)` and describe the features as enabled by default.

#### 7. `company_tui/capabilities/builder.py`, `infrastructure/builder.py`, `infrastructure/builder_page.py`, `templates/scripts.py`, `bootstrap.py`, `presentation/path_screen.py`
- **`bootstrap.py`**: Create ONE shared `config = FileConfig()` in `create_tui_console()` and pass it into both `_build_capability_registry(console, config)` and `_build_update_watch(config)` and `TuiConsole(..., layout=config.layout())` (Fixes **S-10**).
- **`templates/scripts.py:_active_scope()`**: Check `ConfigScope.DRIVEN` first, then `PROJECT`, then `USER` (Fixes **S-09**).
- **`capabilities/builder.py`**:
  - Default `SCOPE_KEY` to active scope (Fixes **S-09**) with `allow_blank=False`.
  - In `_manifest()`: check `self._config.driven_root() or naming.project_root()` (Fixes **S-11c**).
- **`infrastructure/builder.py:281`**: Wrap `int(self.headers.get("Content-Length") or 0)` in `try/except ValueError` returning HTTP `400` (Fixes **S-11d**).
- **`infrastructure/builder_page.py`**:
  - Add `check_on_launch` checkbox in the `Updates` tab (Fixes **S-08**).
  - Update `Experimental` tab copy to reflect default-on; check `doc.experimental[key] !== false`.
  - Fix `parseInt(field.value, 10)` using `Number.isNaN(n)` instead of `||` so `0` reaches validation and reports in "Not taken" (Fixes **S-11e**).
  - Sync `doc = body.document` after clean POSTs when normalized fields differ.
- **`presentation/path_screen.py`**:
  - Add `on_directory_tree_file_selected` handler when `self._files` is `True` (Fixes **S-12**).
  - Add a keybinding/toggle (e.g., `.` or `h` — "Show hidden") to toggle dot-prefixed directories so `~/.dti/` is browsable on demand without cluttering default views (Fixes **S-12**).

---

### 3.2 Phase 2 — Cross-Platform Runtime & macOS Parity

#### 1. Platform-Aware Update Assets (`domain/updates.py`, `capabilities/updates.py`, `application/updates.py`)
- Add platform helpers in `domain/updates.py`:
  ```python
  WINDOWS_ASSET_PATTERN = "*-setup*.exe"
  MACOS_ARM64_ASSET_PATTERN = "*-macos-arm64*.pkg"
  MACOS_X86_64_ASSET_PATTERN = "*-macos-x86_64*.pkg"
  MACOS_UNIVERSAL_ASSET_PATTERN = "*-macos-universal*.pkg"
  ```
  - `default_asset_pattern(platform_name: str = sys.platform, machine: str = platform.machine()) -> str`:
    - `win32` -> `"*-setup*.exe"`
    - `darwin` -> `f"*-macos-{arch}*.pkg"` (where `arch` is `"arm64"` on Apple Silicon, `"x86_64"` on Intel; fallback `"*-macos*.pkg"` if universal builds are chosen — see Section 4.4).
  - Keep `DEFAULT_ASSET_PATTERN = default_asset_pattern()` for backward compatibility.
  - **Cross-OS config portability:** When `asset_pattern` is left at the platform default, `render()` omits it (already true!), so sharing `dti.toml` between Windows and macOS automatically picks the right installer on each OS. In `settings_document.py`, export `""` (or `"auto"`) when unchanged, or detect foreign-OS default patterns cleanly on import.
- Fix `build_kind(command: str)` in `domain/updates.py`:
  - Normalize `PurePosixPath(command.replace("\\", "/")).stem.lower()` so Windows and POSIX paths both parse identically on every OS.
- Update `capabilities/updates.py`:
  - Replace hardcoded `.exe` validation (`target.suffix.lower() != ".exe"`) with `valid_installer_suffixes()` (`{".exe"}` on Windows, `{".pkg", ".tar.gz", ".tgz"}` on macOS) and OS-specific error copy.
- Update `application/updates.py`:
  - Expand `SWEEPABLE = frozenset({".exe", ".pkg", ".dmg", ".tgz", ".gz", ".part"})` (still double-guarded by `self._cache.name == CACHE_DIRECTORY` so nothing outside `~/.dti/updates` can ever be touched).
  - Platform-aware fallback asset filename in `_fetch()` and `_safe_name()`.

#### 2. macOS Self-Update Handover (`infrastructure/handover.py`, `bootstrap.py`)
- Keep `WindowsHandover(HandoverPort)` untouched for Windows (`os.name == "nt"`).
- Add `MacOSHandover(HandoverPort)` for `sys.platform == "darwin"`:
  - Writes a POSIX `/bin/sh` waiter script into `tempfile.gettempdir()` (`dti-update-<pid>.sh`, `chmod 0o700`) with zero interpolated paths — all inputs passed via positional args (`$1`=wait_pid, `$2`=timeout, `$3`=installer_path, `$4`=relaunch_path, `$5`=log_path).
  - Spawns with `subprocess.Popen(["/bin/sh", str(script), ...], start_new_session=True, close_fds=True, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)`.
  - Script flow (mirrors Windows `docs/decisions/0004` exactly):
    1. Poll `kill -0 "$WAIT_PID"` every 0.25s up to `$TIMEOUT` seconds until the TUI process exits.
    2. Install silently without admin prompt:
       - For `.pkg`: `installer -pkg "$INSTALLER" -target CurrentUserHomeDirectory`
       - For `.tar.gz`: extract into staging dir beside install root and atomically swap.
    3. On non-zero exit: keep log file in `$TMPDIR` and run `open "$INSTALLER"` so macOS Installer.app shows the failure visibly (mirroring Windows' visible retry without `/S`).
    4. On exit 0: delete log file; if frozen (`$RELAUNCH` non-empty), relaunch in a new Terminal session (or print/open if appropriate) and remove the waiter script itself.
- Add `default_handover() -> HandoverPort` factory in `infrastructure/handover.py` returning `WindowsHandover()` on `nt` and `MacOSHandover()` on `darwin`; wire `bootstrap.py` to call `default_handover()`.

#### 3. POSIX Terminal Safety & Clipboard Fallback (`infrastructure/terminal_window.py`, `presentation/run_screen.py`)
- **`terminal_window.py`**:
  - On POSIX (`os.name != "nt"`), save `termios.tcgetattr(sys.__stdin__.fileno())` in `console_modes()` (when `isatty()`) and restore via `termios.tcsetattr(..., TCSADRAIN, saved)` in `release_terminal()` alongside writing `_RELEASE_SEQUENCE`.
- **`run_screen.py`**:
  - In `_copy_terminal()`, after `self.app.copy_to_clipboard(transcript)`, on `sys.platform == "darwin"` also pipe `transcript` to `pbcopy` (non-blocking / short timeout, silent fallback if unavailable) so the **COPY** button works in Apple Terminal.app as well as iTerm2/Ghostty/WezTerm.
- **`domain/script_config.py:428`**:
  - Make `command_preview()` OS-aware (`./script.sh` or `./script.ps1` on POSIX vs `.\script.ps1` on Windows, or infer prefix from the action's declared command).

---

### 3.3 Phase 3 — macOS Build, Packaging & CI Pipeline

Create a clean macOS automation suite that mirrors Windows' `script.ps1` + `scripts/*.ps1` one-to-one without duplicating logic in GitHub Actions YAML:

```text
script.sh                          # macOS/POSIX entry point (discovers scripts/mac/*.sh, mirrors script.ps1)
.gitattributes                     # Enforce LF for source/scripts/docs; prevent Windows/macOS CRLF churn
scripts/mac/
├── lib/
│   ├── app-version.sh             # Reads/bumps VERSION, pyproject.toml, uv.lock, git tags (parity with app-version.ps1)
│   └── signing.sh                 # Ad-hoc codesign, Developer ID codesign, productsign, notarytool
├── setup-dev-env.sh               # Recreates macOS .venv via uv/python3.12+, installs -e ., pyinstaller, ruff
├── check-all.sh                   # Same gate as check-all.ps1: python, textual, unittest, version, secrets, ruff, shellcheck, -Build smoke test
├── build-app.sh                   # PyInstaller --onedir freeze (VERSION:.), verifies VERSION bundled, codesigns binary
├── build-installer.sh             # Builds per-user .pkg (pkgbuild + productbuild) AND portable .tar.gz
├── benchmark.sh                   # Interleaved min-of-N startup benchmark (--version, list, doctor)
└── pkg/
    ├── distribution.xml.tmpl      # productbuild XML enabling CurrentUserHomeDirectory (no sudo)
    ├── postinstall.sh             # Symlinks dti / dti-debug into ~/.local/bin, safely updates shell rc PATH block
    └── uninstall.sh               # Cleanly removes install dir, symlink, PATH block; preserves ~/.dti store
```

And update CI workflows:
- **`.github/workflows/check.yml`**: Add a `check-macos` job (`runs-on: macos-latest`) calling `./script.sh setup-dev-env --lint` and `./script.sh check-all`.
- **`.github/workflows/release.yml`**: Add a `release-macos` job (`runs-on: macos-latest`, Apple Silicon) alongside `release-windows` (`windows-latest`), sharing the same tag/version bump so a single GitHub Release publishes both:
  - Windows: `dti-<version>-setup[-released].exe`
  - macOS (arm64): `dti-<version>-macos-arm64[-released].pkg` and `dti-<version>-macos-arm64[-released].tar.gz`

---

### 3.4 Phase 4 — Tests, Decisions & Copy Sync

- **New test suites:**
  - `tests/test_settings_capability.py`: verifies `SettingsCapability._save()` preserves `updates`, `layout`, `experimental` flags, custom stack entries, active scope defaulting, and re-run refresh.
  - `tests/test_advanced_capability.py`: verifies `AdvancedCapability._save()` preserves `layout`, preserves `channel` when dropdown untouched, preserves/edits `check_on_launch`, `RESET_KEY` resets both update source and feature flags to defaults, and default-on opt-out round-trips.
  - `tests/test_macos_handover.py`: verifies `MacOSHandover` waiter script ordering (`kill -0` wait before install), positional args (no shell injection on awkward paths with quotes/spaces/`$`), log preservation on failure / removal on success, missing installer refusal, and `default_handover()` selection.
- **Updated test suites:**
  - `tests/test_interactive_gate.py`, `tests/test_browser.py`, `tests/test_layout.py`, `tests/test_settings_document.py`, `tests/test_updates.py`, `tests/test_auto_update.py`.
- **Docs & ADRs:**
  - Amend `docs/decisions/0004`, `0005`, `0006`, `0007`.
  - Add `docs/decisions/0008-macos-build-and-packaging.md`.
  - Record findings S-01, S-03, S-04, S-05, S-09 in `docs/pitfalls.md`.
  - Update `CLAUDE.md`, `README.md`, `company_tui/presentation/hints.py`.
  - Run `graphify update .`.

---

## 4. Build Processes (macOS Local & CI)

### 4.1 Prerequisites & Clean Environment Setup

Because the repository currently has a Windows `.venv/` and macOS ships system Python 3.9.6 at `/usr/bin/python3`, first-time setup on a Mac must create a clean macOS virtualenv on CPython **3.12 or 3.13** (recommended for PyInstaller stability; verify 3.14/3.15 before switching):

```sh
# 1. Install uv (recommended) or Homebrew Python 3.13
brew install uv

# 2. Remove stale Windows .venv if present
rm -rf .venv

# 3. Create a macOS virtualenv with pinned Python 3.13 and install deps + build/lint tools
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -e . pyinstaller ruff

# 4. Verify interpreter, tests, and CLI
.venv/bin/python -m company_tui check
.venv/bin/ruff check company_tui tests
```

> **Note on `VERSION` vs `uv.lock`:** Before running `check-all`, reconcile `uv.lock` (`0.4.1+34`) with `VERSION` / `pyproject.toml` (`0.4.0+31`) via `uv lock` (or bump cleanly) so the version-consistency gate passes.

---

### 4.2 Local Build Pipeline (`./script.sh`)

Every command mirrors `.\script.ps1` and accepts `--help`:

```sh
./script.sh                                       # list commands discovered from scripts/mac/
./script.sh setup-dev-env --build --lint          # create macOS .venv, install editable pkg + pyinstaller + ruff
./script.sh check-all                             # full local/CI gate (python, textual, unittest, version, secrets, ruff)
./script.sh check-all --build                     # gate + freeze + smoke-test frozen `dti --version`
./script.sh build-app [--released] [--clean] [--sign] [--optimize 0|1|2] [--python 3.13]
./script.sh benchmark [--levels 0,1,2] [--runs 9]
./script.sh build-installer [--released] [--sign] [--notarize]
```

#### Step-by-Step `build-app.sh` Process

1. **Read version** from `VERSION` (`x.y.z+n`) and detect host architecture (`uname -m` -> `arm64` or `x86_64`).
2. **Resolve interpreter** (`.venv/bin/python`, or `uv run --python <spec> --no-project --with pyinstaller --with 'textual>=8.2,<9' -- python` when `--python` is passed). Refuse Python `< 3.11`.
3. **Freeze with PyInstaller (`--onedir`, `--console`)**:
   ```sh
   "$PYTHON" -m PyInstaller \
     --noconfirm \
     --onedir \
     --console \
     --name dti \
     --distpath build/frozen \
     --workpath build \
     --specpath build \
     --add-data "$(pwd)/VERSION:." \
     --collect-all textual \
     --paths "$(pwd)" \
     --optimize "$OPTIMIZE" \
     "$(pwd)/scripts/launch.py"
   ```
   > **Critical macOS difference:** `--add-data` uses `:` (`SRC:DEST`), **never** `;` (Windows).
4. **Stage output** to `dist/dti-<version>-macos-<arch>/` containing:
   - `dti` (or renamed to `dti-debug` during debug packaging — onedir bootloader resolves `_internal/` by directory, not executable name)
   - `_internal/` (Python runtime, stdlib, `textual`, and bundled `VERSION`)
5. **Assert `VERSION` landed** in the bundle (fail immediately if missing, preventing silent `v0.0.0+0`).
6. **Code-sign the bundle** (required on Apple Silicon even for local runs):
   - Default/local: ad-hoc sign every `.dylib`/`.so` and the main executable (`codesign --force --sign - ...`).
   - `--sign` with Developer ID: hardened runtime + timestamp (`codesign --force --options runtime --timestamp --sign "$APPLE_SIGN_IDENTITY" ...`).
7. **Smoke-test the frozen binary**:
   ```sh
   ./dist/dti-<version>-macos-<arch>/dti --version
   ./dist/dti-<version>-macos-<arch>/dti list
   ./dist/dti-<version>-macos-<arch>/dti doctor
   ```

---

### 4.3 Install Layout & Release/Debug Isolation

Mirrors Windows' `INSTALL_SLUG` rule (`CLAUDE.md` & `docs/pitfalls.md 6.6`) so a debug build **installs beside** the release build and never overwrites it or collides on PATH:

| Property | Official Release (`--released`) | Debug Build (default) |
|---|---|---|
| `INSTALL_SLUG` | `dti` | `dti-debug` |
| Install directory (per-user, no `sudo`) | `~/Library/Application Support/dti` | `~/Library/Application Support/dti-debug` |
| Executable inside install dir | `dti` | `dti-debug` |
| PATH symlink | `~/.local/bin/dti` | `~/.local/bin/dti-debug` |
| `pkgbuild` identifier | `com.dti.toolbox` | `com.dti.toolbox.debug` |
| Update state file | `~/.dti/updates.json` | `~/.dti/updates-debug.json` |
| Shared user store (preserved on uninstall) | `~/.dti/` | `~/.dti/` |
| Release asset names | `dti-<ver>-macos-<arch>-released.pkg`<br>`dti-<ver>-macos-<arch>-released.tar.gz` | `dti-<ver>-macos-<arch>.pkg`<br>`dti-<ver>-macos-<arch>.tar.gz` |

> **Why rename the inner binary to `dti-debug`?** `bootstrap.running_build()` calls `build_kind(sys.executable)`. Naming the actual frozen binary `dti-debug` ensures `running_build()` returns `BUILD_DEBUG` even after symlink resolution, keeping release and debug update lines strictly isolated.

#### Safe PATH Registration (`postinstall.sh` / `uninstall.sh`)

- Target bin dir: `$HOME/.local/bin` (user-owned, zero `sudo` needed).
- Idempotently appends a clearly fenced block to `~/.zprofile` (macOS default login shell `zsh`) and `~/.bash_profile` (if present):
  ```sh
  # >>> dti PATH >>>
  export PATH="$HOME/.local/bin:$PATH"
  # <<< dti PATH <<<
  ```
- On uninstall, `uninstall.sh` removes only the fenced block (never truncating or rewriting unrelated PATH entries) and leaves `~/.dti/` intact.

---

### 4.4 Packaging Formats (`.pkg` Primary + `.tar.gz` Portable)

#### Format 1: Per-User `.pkg` (Primary Installer — macOS equivalent of `*-setup*.exe`)

Built with native macOS `pkgbuild` + `productbuild` (no third-party tools):

```sh
# 1. Stage payload into clean root
#    stage/Library/Application Support/<INSTALL_SLUG>/{<COMMAND>, _internal/, uninstall.sh}

# 2. Build component package
pkgbuild \
  --root build/pkg-root \
  --scripts scripts/mac/pkg/scripts \
  --identifier "$PKG_ID" \
  --version "$PLAIN_VERSION" \
  --install-location "/" \
  "build/${INSTALL_SLUG}-component.pkg"

# 3. Wrap with distribution XML allowing CurrentUserHomeDirectory (no admin prompt)
productbuild \
  --distribution build/distribution.xml \
  --package-path build \
  "dist/${OUT_NAME}.pkg"
```

Key `<domains>` setting in `distribution.xml`:
```xml
<domains enable_anywhere="false" enable_currentUserHome="true" enable_localSystem="false"/>
```

**Why `.pkg` with `enable_currentUserHome="true"` is ideal:**
- Double-clicking opens Apple's native Installer UI with **no administrator password prompt**.
- Installing from CLI or in-app self-update runs silently:
  ```sh
  installer -pkg "$PKG_PATH" -target CurrentUserHomeDirectory
  ```
- `preinstall` removes the previous `~/Library/Application Support/<INSTALL_SLUG>` directory cleanly before unpacking, avoiding stale `_internal/` files (same invariant as Windows NSIS `UninstallPrevious`).

#### Format 2: Portable `.tar.gz` (CLI / Homebrew / Air-gapped)

```sh
tar -C dist -czf "dist/${OUT_NAME}.tar.gz" "dti-${VERSION}-macos-${ARCH}"
```
- Pairs with an `install.sh` inside the archive for one-command terminal installs and enables a future Homebrew Tap formula (`brew install <tap>/dti`) with zero extra build steps.

#### Why `.dmg` / `.app` Is Deferred (Optional Future Phase)
- DTI is a `--console` Textual TUI, not a Cocoa window app. A `.app` bundle on macOS requires a launcher shim that invokes `Terminal.app` / `iTerm2` via AppleScript/shell to open a TTY. Keep `.pkg` + `.tar.gz` as the clean Phase 3 deliverables; add a `.app` + `.dmg` wrapper later only if non-terminal Finder launching is requested.

---

### 4.5 Code Signing & Notarization

| Mode | When Used | Mechanism | Gatekeeper Result |
|---|---|---|---|
| **Ad-hoc (`codesign -s -`)** | Local dev builds & unsigned CI rehearsals | Signs all Mach-O binaries inside `_internal/` and `dti` with ad-hoc signature (`-`). **Mandatory on Apple Silicon** so the kernel allows execution. | Runs locally; downloaded copies show macOS quarantine warning until `xattr -dr com.apple.quarantine` or System Settings → Open Anyway. |
| **Developer ID + Notarization** | Official signed CI releases (`sign = true`) | 1. Import `.p12` into ephemeral keychain (`security create-keychain`).<br>2. Sign every nested `.so`/`.dylib` and main binary with `Developer ID Application` (`--options runtime --timestamp`).<br>3. Sign `.pkg` with `Developer ID Installer` (`productsign`).<br>4. Submit via `xcrun notarytool submit --wait`.<br>5. Staple ticket via `xcrun stapler staple`. | Passes Gatekeeper silently on any Mac with zero warnings. |

#### CI Secrets Needed for Signed macOS Releases (Parallel to Windows' 3 Secrets)

- `APPLE_APP_CERT_P12_B64` / `APPLE_APP_CERT_PASSWORD` — Developer ID Application cert (or shared `.p12` containing both Application + Installer certs)
- `APPLE_INSTALLER_CERT_P12_B64` / `APPLE_INSTALLER_CERT_PASSWORD` — Developer ID Installer cert
- `APPLE_SIGN_IDENTITY` / `APPLE_INSTALLER_IDENTITY` — Certificate CN strings
- `APPLE_NOTARY_KEY_B64`, `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER_ID` — App Store Connect API key for `xcrun notarytool` (preferred over app-specific Apple ID passwords)

Just like Windows (`scripts/lib/signing.ps1`), missing signing credentials on a local machine should **not** block building — fall back to ad-hoc signing with a clear warning that the artifact is not notarized.

---

### 4.6 In-App Self-Update Handover on macOS

```text
Running dti (PID 1234)
   │
   ├── 1. User confirms update (Ctrl+U or Check for Updates)
   ├── 2. MacOSHandover writes $TMPDIR/dti-update-1234.sh (chmod 700)
   ├── 3. Popen(["/bin/sh", script, 1234, 120, pkg_path, relaunch_bin, log_path],
   │            start_new_session=True, stdin/stdout/stderr=DEVNULL)
   ├── 4. dti shows InstallingScreen (INSTALL_PAUSE), releases terminal, exits 0
   │
Detached Waiter ($TMPDIR/dti-update-1234.sh)
   │
   ├── 5. Loops `kill -0 1234` until PID 1234 exits (up to 120s timeout)
   ├── 6. Runs `installer -pkg "$PKG" -target CurrentUserHomeDirectory`
   ├── 7a. Exit 0: removes log + waiter script; relaunches updated `dti` if frozen
   └── 7b. Exit != 0: keeps log at $TMPDIR/dti-update-1234.log, runs `open "$PKG"`
           so macOS Installer UI reports the failure visibly
```

---

### 4.7 Benchmarking & Release Workflow (GitHub Actions)

#### Benchmarking (`scripts/mac/benchmark.sh`)
- Mirrors `scripts/benchmark.ps1`: interleaved rounds (`--runs 9`), reports **minimum** elapsed ms for `--version`, `list`, and `doctor` plus bundle size in MB and repeat-run spread.
- Uses `python3 -c 'import time; ...'` (monotonic `time.perf_counter_ns()`) because macOS BSD `date` does not support `%N` nanoseconds.

#### GitHub Actions Multi-OS Release Flow (`.github/workflows/release.yml`)

```text
Job 1: prepare (ubuntu-latest or windows-latest)
   └── Runs bump-version (or rehearsal -WhatIf), outputs version + tag

Job 2a: build-windows (runs-on: windows-latest)     Job 2b: build-macos (runs-on: macos-latest)
   ├── .\script.ps1 setup-dev-env -Build -Lint         ├── ./script.sh setup-dev-env --build --lint
   ├── .\script.ps1 check-all                          ├── ./script.sh check-all
   ├── .\script.ps1 build-app ...                      ├── ./script.sh build-app ...
   ├── .\script.ps1 benchmark -NoBuild                 ├── ./script.sh benchmark --no-build
   ├── .\script.ps1 build-installer ...                ├── ./script.sh build-installer ...
   └── upload artifacts (*-setup*.exe)                 └── upload artifacts (*-macos-*.pkg, *.tar.gz)

Job 3: publish (needs: [prepare, build-windows, build-macos], if: inputs.tag)
   ├── Push release commit + tag
   └── `gh release create <tag>` attaching BOTH Windows & macOS assets + generated release notes
```

- Preserves the rehearsal-by-default invariant (`tag = false` uploads both OS installers as 14-day workflow artifacts and pushes/publishes nothing).
- Caches `pip`/`uv` and PyInstaller caches (`~/Library/Application Support/pyinstaller` on macOS, `%LOCALAPPDATA%\pyinstaller` on Windows) — never `.venv`.

---

### 4.8 Pre-Release Verification Checklist

- [ ] Clean macOS `.venv` (Python 3.12/3.13); `VERSION`, `pyproject.toml`, and `uv.lock` agree.
- [ ] `./script.sh check-all --build` passes with zero failures (tests, list, doctor, version, secrets, ruff, frozen smoke test).
- [ ] Settings regression checks (manual + automated):
  - [ ] Saving `[05] Settings` preserves `[updates]`, `[layout]`, `[experimental]`, and custom packs.
  - [ ] Saving `[09] Advanced` preserves `[layout]`, preserves untouched `Channel` (`prerelease`/`any`), preserves `check_on_launch`.
  - [ ] `Reset these to defaults` in `[09] Advanced` resets both update source and all 3 feature toggles to defaults.
  - [ ] Fresh machine (no `dti.toml`): `interactive_lists`, `timed_prompts`, and `browser_view` are all `True` by default; turning any one OFF writes `<key> = false` and survives restart.
  - [ ] Clicking "Run again" after saving Settings/Advanced refreshes `Reading now` / `Would ask` / store status and resets one-shot toggles.
  - [ ] Opening `[09] Advanced` or `[10] Builder` inside a repo with `./dti.toml` defaults `Save to` to the active scope (no silent shadowing).
  - [ ] `[10] Builder` opens in macOS default browser, saves cleanly, validates `bundle_prefix` & `UpdateSource`, and never writes unquoted invalid TOML keys.
- [ ] macOS runtime checks:
  - [ ] Frozen `dti` launches cleanly in Apple Terminal.app and iTerm2/Ghostty, displays correct `VERSION`.
  - [ ] `Ctrl+C` / `Ctrl+Q` / `Esc` quit restores terminal cleanly (cursor visible, echo on, no mouse escape spam).
  - [ ] Terminal **COPY** button populates macOS clipboard (`pbpaste` returns transcript) even in Apple Terminal.app.
  - [ ] Per-user `.pkg` installs without `sudo`; `dti` and `dti-debug` coexist without overwriting each other.
  - [ ] Local `.pkg` update handover replaces running `dti` cleanly after exit.
  - [ ] `graphify update .` run after code changes.

---

## 5. Open Questions & Custom Bug Notes

Before starting Phase 1 implementation, confirm the following:

1. **Additional settings bugs you encountered:** Compare Section 2.1 (`S-01` through `S-12`) against the specific bugs you ran into while testing Settings/Advanced/Builder — add any extra repro steps or edge cases here so nothing is missed.
2. **macOS target architectures:** Do you want Apple Silicon only (`arm64`, `macos-latest` single runner — fastest, matches this Mac mini), or both `arm64` + Intel `x86_64`?
3. **macOS signing readiness:** Do you already have an Apple Developer ID Application + Installer certificate (for notarized public `.pkg` releases), or should Phase 3 start with ad-hoc signing + `.pkg`/`.tar.gz` and wire Developer ID secrets as optional (matching Windows' unsigned fallback)?
4. **Reset behavior in `[09] Advanced`:** Should `Reset these to defaults` restore `repository` to the built-in `DEFAULT_REPOSITORY` (`jnsbnmndz/ikaika_tui`) and all 3 feature flags to `True` (recommended, since built-in defaults have updates + all 3 features on), or clear `repository` to `""`?
