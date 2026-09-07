# Generic Developer Toolbox

A scalable Python terminal application for development workflows. The first capability boundary covered scaffolding; the same application now also builds, deploys, runs a project's own commands, and maintains itself.

The version is not written here. It lives in `VERSION` at the repository root, one line, `x.y.z+n` — a version quoted in a README is one that goes stale the first time nobody remembers to change it, and this one had been reading `v0.0.0+1` for some time. `presentation/branding.py` reads that file; `domain/naming.py` holds every name the product answers to.

Scaffold and Build both drill down through the same two questions: *what* do you want to do, then *which stack* do you want to do it for. Each stack is a versioned template pack; Flutter and React are wired in as "not available yet" placeholders, and Python is a fully working reference pack that creates a real project on disk (with a preview and confirmation prompt) and runs a real build check.

`python -m company_tui` (no arguments) opens a real interactive terminal UI built with [Textual](https://textual.textualize.io/): an animated splash screen, a navy-and-gold theme, card-based menus you can click through or navigate with the arrow keys, and a persistent "Activity" output log. `list` and `doctor` stay plain, synchronous, scriptable stdout with no terminal takeover, so they still work well in scripts and CI.

## Run

Python 3.11 or newer is required.

```sh
python -m company_tui                  # interactive Textual UI
python -m company_tui --start scripts  # open straight on a capability
python -m company_tui list             # plain stdout, scriptable
python -m company_tui doctor           # plain stdout, scriptable
python -m company_tui check            # the gate: tests, list and doctor
```

Install the console command locally when needed. Two names are installed for one entry point — `generic` matches what the product is called, and `company` is kept so anything already invoking it keeps working:

```sh
python -m pip install -e .
generic
```

Run the tests:

```sh
python -m unittest discover
python -m company_tui check              # and everything else the gate covers
python -m company_tui check --install-hook   # as a pre-push hook
```

The version is `VERSION` at the repository root — one line, `x.y.z+n`, read by
`presentation/branding.py`. A release rewrites that file and nothing restates it.

## Structure

```text
company_tui/
├── application/      orchestration, capability registry, template pack registry
├── capabilities/     independently executable product features (scaffold, build, deploy, scripts, settings, doctor, app_setup, updates, advanced)
├── domain/           stable models and interfaces
├── infrastructure/   operating system and external tool adapters
├── presentation/     Ui protocol, PlainConsole (stdout), TuiConsole (Textual app + screens + chrome)
├── templates/        one versioned template pack per stack (flutter, react, python, ...)
├── bootstrap.py      dependency composition
├── cli.py            command-line entry point
└── __main__.py       python -m entry point
```

Dependencies point inward. Presentation and infrastructure implement the edges, application coordinates work, and domain contracts remain independent. Template packs depend only on domain ports, the same rule infrastructure follows. Each new function enters as a capability and is registered in `bootstrap.py`.

Every interactive step in the domain/application/capability layers is `async` — `Application.run()`, `Capability.execute()`, and `TemplatePack.scaffold()`/`.build()` all await the console. This is what lets the same capability and template-pack code run unchanged against either presentation implementation:

- `presentation/plain_console.py: PlainConsole` — today's numbered `input()`/`print()` console, used by `list`/`doctor`. Its interactive methods are `async def` for interface compatibility but do no real awaiting.
- `presentation/tui_console.py: TuiConsole` — a `textual.app.App` used by the interactive `python -m company_tui` path. It answers each `Ui` method by pushing a screen from `presentation/screens.py` (`SplashScreen`, `CardMenuScreen`, `ConfirmScreen`, `InputScreen`, `ContinueScreen`) and awaiting `push_screen_wait()` from a worker.

## Branding

- `presentation/branding.py` holds the tagline, the version and `APP_THEME` — a Textual `Theme`: a deep navy primary, a warm gold accent, near-black navy background. `TuiConsole` registers and activates it on mount. The name itself is not here: it comes from `domain/naming.py`, which is the single place every name derives from `APP_SLUG`, so the wordmark and the theme name cannot drift from it. `SPLASH_MARK` is a deliberately abstract placeholder — it used to be one company's logo, which is exactly what a generic toolbox should not open with; regenerate it from an image with `python -m tools.blockify <image>.png --rows 13 --name SPLASH_MARK`.
- `presentation/chrome.py` is the frame every screen is composed inside: `AppFrame` (outer border), `AppHeader` (logo mark, name, tagline, version, and the working directory as a status), and `AppFooter` (key hints on the left, `APP_SIGNATURE` on the right). It fills the terminal by default; `FRAME_WIDTH`/`FRAME_HEIGHT` at the top of the module can be set to viewport units to float the app as a smaller centred panel instead.
- Every key hint is also a button: hovering one lights it in the accent colour and clicking it presses the key it names, so `Esc`, `Ctrl+R`, `⌃T` and the rest work with the mouse as well as the keyboard. Hints that name a range rather than one key (`↑↓/←→`, `1–9`) stay quiet, as does a key that would do nothing at that moment. Tabs light up under the pointer for the same reason — you can see what a click is about to hit before you make it.
- The run panel says what it wants before you press anything: required fields carry a gold `*`, a line under the form names whatever is still missing, and the terminal half says it is empty rather than just being empty. Press Run without filling something in and that same line goes red with the cursor already on the field it is about.
- Every context has its own tabs. React Native's runs are in React Native's strip, Flutter's in Flutter's, each numbered from one — start a scaffold, back out, pick another stack, and you arrive on an empty first tab with the first run still going where you left it. Menu cards say what is behind them (`2 running`), counted down the whole branch, so a run left going is never somewhere you have to guess at.
- A tab stays after its run ends. Walk back into the stack and it is there — the output, the time it ran, and the form still holding what you typed, ready to send again. `⌃W` closes one when you are done with it.
- `Ctrl+B` lists every run there is, whichever stack it belongs to, and takes you to the one you pick.
- Esc is always one step back. From a run panel with work in flight it leaves the run going in its own tab and puts back the menu that started it, so making a second project with a different stack does not mean walking in from the front again; the running count in the header and `Ctrl+B` get you back to it.
- The stdin row at the foot of the terminal pane turns accent while a run is actually waiting on an answer, so a question in a tab you are not looking at does not read as a run that has quietly stopped.
- Esc walks back through the menus, and walking out of the last one asks before it closes the app — mashing it to get to the top cannot overshoot into quitting. `Ctrl+Q` and `Ctrl+C` leave straight away unless a run is still going, which always asks first.
- `presentation/icons.py` maps each capability/scaffold-target/stack key to the box-drawing line art on its card (`art_for(key)`, with a fallback for anything unmapped) — add an entry here when a new capability, target, or stack pack is registered. It is line art rather than emoji because terminals disagree about emoji width, which shifts the layout, and their fixed color competes with the accent.
- `presentation/hints.py` maps the same keys to the longer one-line detail shown at the bottom of the menu for whichever entry has focus (`hint_for(key, fallback)`), so a card description can stay short without losing the explanation.
- `TuiConsole` tracks a breadcrumb of the choices it has served and shows it above each menu title (`Scaffold › New Project`) and as the border title of the input and confirm dialogs, so a workflow you walked away from still says where you are. Cancelling a step re-asks the step before it instead of dropping out of the workflow; only backing out of the first step ends it, which `Capability.execute()` reports as `CANCELLED`.
- `presentation/card.py: Card` is the clickable, keyboard-focusable, animated building block behind every menu — a numbered badge, line art, a name, a description, and a `[n]` hotkey. It has no fill in any state — a double accent border marks the focused card, and hovering focuses the card under the mouse so there is only ever one highlight. Cards are height-capped so a maximised terminal doesn't stretch them, and lay out in a grid at most three wide — a fourth entry wraps to a second row instead of squeezing the first. Below 30 rows (or when the row would be too narrow) the same card renders as a single compact row instead; only CSS decides which.

## Building and releasing

Everything goes through one entry point, and GitHub Actions calls the same file rather
than restating the steps in YAML — a workflow that lists its own steps is a second,
silently diverging answer to what a release is.

```powershell
.\script.ps1                                  # what commands there are
.\script.ps1 <command> -Help                  # one command's own switches

.\script.ps1 setup-dev-env -Build -Lint       # make a machine able to build
.\script.ps1 check-all                        # the gate; -InstallHook wires it to pre-push
.\script.ps1 setup-signing                    # the release and debug certificates
.\script.ps1 bump-version -Bump patch         # rewrite VERSION, commit, tag
.\script.ps1 build-app -Sign                  # freeze it with PyInstaller
.\script.ps1 build-installer -Sign            # wrap it in an NSIS installer
```

Commands are **discovered**, not listed: a `.ps1` in `scripts\` is a command named
after its file, so the listing and the folder cannot disagree.

### The version, and why the build number matters

`VERSION` holds `x.y.z+n` and `pyproject.toml` is rewritten to match. The build number
rises **globally**, across version names, and comes from the **tags** rather than from
`VERSION`: `1.1.9+7` is followed by `1.2.0+8`, never `1.2.0+1`. An installer compares
that number, so a reset makes an upgrade look older than what is already installed.
A number a tag has already claimed is never handed out twice, and that is checked
before anything is built.

Which means a release has to be **tagged**. `bump-version` commits and tags but pushes
nothing — publishing is a decision, and a build tool that pushes on your behalf is one
nobody can rehearse.

### `-released` is what makes a build official

    v1.2.0              a debug build
    v1.2.0-released     the official release

One version can carry both: the same source is tagged debug while it is being tested
and released once it ships. Both share one build number, because the number belongs to
the source. The release workflow publishes debug builds as prereleases, so
`Check for Updates` — which asks for the latest official release — cannot offer one.

### Signing

Two certificates, a release identity and a debug one. A debug installer is signed too,
so a test build is not an Unknown Publisher either, but with its own certificate, so
nothing about a test build touches the trust the real release signature depends on.

`setup-signing` uses the certificate already present if it matches its committed
checksum, otherwise fetches it from the shared link, and only generates one when there
is genuinely nothing to fetch — generating is a *new identity*, and every installer
signed with the old one stops matching it. CI runs it with `-FetchOnly`, which refuses
to generate at all.

| What | Where | Committed? |
|---|---|---|
| The private keys | `certs/*.pfx` | **no** |
| The password | `.generic_configs/signing.env` | **no** |
| Their checksums | `.generic_configs/*.pfx.sha256` | yes, deliberately |
| The share links | `.generic_configs/share.env` | yes |

The checksums are the point of that split: a `.pfx` arrives over a link from a machine
nobody here controls, and a same-named file is not the same file. The link is safe to
commit because the password is not there — fetching the file gets you a container you
cannot open. A new machine needs the password out of band.

Nothing fails when a certificate is missing: the build says the artifacts are unsigned
and carries on. Unsigned means an Unknown Publisher warning, not a broken installer.

### The installer

NSIS, per-user under `%LOCALAPPDATA%\Programs`, so it needs no administrator prompt — a
developer tool that demands one is a tool people install once and stop updating. An
upgrade runs the old uninstaller first: a PyInstaller folder's contents change between
versions, and copying a new build over an old one leaves whatever the new one no longer
ships sitting on the import path.

## Template packs

`react_native` scaffolds a new project by shallow-cloning `https://github.com/JDM-Github/react_native_structure.git` and then deleting the clone's `.git`, so what you get is the structure with no history and no remote pointing at the template. The clone runs through `ProcessRunner` as an argument array and the delete through `FileSystemPort.remove_tree`, both previewed and confirmed before anything touches disk.

Each stack under `templates/<stack>/` is two files:

- `behavior.py` — the editable hooks (`scaffold_new_project`, `scaffold_controller`, `build`). This is the only file meant to change per stack.
- `pack.py` — a thin adapter that implements the `TemplatePack` contract and dispatches to `behavior.py`. Boilerplate; not hand-edited per stack.

To add a new stack: copy `templates/_skeleton/`, rename the directory, set `STACK_NAME` in `behavior.py`, fill in the three functions, and register the pack in `bootstrap.py`. `templates/python/` is the reference implementation to model real behavior after — its `scaffold_new_project` previews the files it will write, asks for confirmation, then writes them; its `build` runs a real version check.

## Growth path

The next useful slice is fleshing out the Flutter and React `behavior.py` hooks with real tooling calls (`flutter create`, `npm create vite@latest`, etc.) behind the existing `ProcessRunner`/`FileSystemPort` ports, plus manifest-driven variable validation for scaffold prompts.

`textual` is the only third-party dependency. If a stack's real behavior ever needs another one (an SDK client, a templating engine), add it deliberately and put it behind a port, the same way `ProcessRunner`/`FileSystemPort` keep the domain free of concrete tools.

