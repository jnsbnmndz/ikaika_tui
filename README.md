# IKAIKA Developer Toolbox

**IKAIKA** · v0.0.0+1 — a scalable Python terminal application for company development workflows. The first capability boundary covers scaffolding, while the same application can grow into build, compile, test, deploy, environment, and maintenance workflows.

Scaffold and Build both drill down through the same two questions: *what* do you want to do, then *which stack* do you want to do it for. Each stack is a versioned template pack; Flutter and React are wired in as "not available yet" placeholders, and Python is a fully working reference pack that creates a real project on disk (with a preview and confirmation prompt) and runs a real build check.

`python -m company_tui` (no arguments) opens a real interactive terminal UI built with [Textual](https://textual.textualize.io/), branded for IKAIKA: an animated splash screen, a navy-and-gold theme drawn from the company logo, card-based menus you can click through or navigate with the arrow keys, and a persistent "Activity" output log. `list` and `doctor` stay plain, synchronous, scriptable stdout with no terminal takeover, so they still work well in scripts and CI.

## Run

Python 3.11 or newer is required.

```sh
python -m company_tui                  # interactive Textual UI
python -m company_tui --start scripts  # open straight on a capability
python -m company_tui list             # plain stdout, scriptable
python -m company_tui doctor           # plain stdout, scriptable
python -m company_tui check            # the gate: tests, list and doctor
```

Install the `company` command locally when needed:

```sh
python -m pip install -e .
company
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
├── capabilities/     independently executable product features (scaffold, build, scripts, doctor, ...)
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

- `presentation/branding.py` holds the IKAIKA name, tagline, version, and `IKAIKA_THEME` — a Textual `Theme` with colors drawn from the company logo (`project-estimator/images/Ika-ika_logo.png` in the wider IKAIKA workspace): a deep navy primary, a warm gold accent, near-black navy background. `TuiConsole` registers and activates it on mount.
- `presentation/chrome.py` is the frame every screen is composed inside: `AppFrame` (outer border), `AppHeader` (logo mark, name, tagline, version, and the working directory as a status), and `AppFooter` (key hints on the left, `IKAIKA Engineering` on the right). It fills the terminal by default; `FRAME_WIDTH`/`FRAME_HEIGHT` at the top of the module can be set to viewport units to float the app as a smaller centred panel instead.
- Every key hint is also a button: hovering one lights it in the accent colour and clicking it presses the key it names, so `Esc`, `Ctrl+R`, `⌃T` and the rest work with the mouse as well as the keyboard. Hints that name a range rather than one key (`↑↓/←→`, `1–6`) stay quiet, as does a key that would do nothing at that moment. Tabs light up under the pointer for the same reason — you can see what a click is about to hit before you make it.
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

## Template packs

`react_native` scaffolds a new project by shallow-cloning `https://github.com/JDM-Github/react_native_structure.git` and then deleting the clone's `.git`, so what you get is the structure with no history and no remote pointing at the template. The clone runs through `ProcessRunner` as an argument array and the delete through `FileSystemPort.remove_tree`, both previewed and confirmed before anything touches disk.

Each stack under `templates/<stack>/` is two files:

- `behavior.py` — the editable hooks (`scaffold_new_project`, `scaffold_controller`, `build`). This is the only file meant to change per stack.
- `pack.py` — a thin adapter that implements the `TemplatePack` contract and dispatches to `behavior.py`. Boilerplate; not hand-edited per stack.

To add a new stack: copy `templates/_skeleton/`, rename the directory, set `STACK_NAME` in `behavior.py`, fill in the three functions, and register the pack in `bootstrap.py`. `templates/python/` is the reference implementation to model real behavior after — its `scaffold_new_project` previews the files it will write, asks for confirmation, then writes them; its `build` runs a real version check.

## Growth path

The next useful slice is fleshing out the Flutter and React `behavior.py` hooks with real tooling calls (`flutter create`, `npm create vite@latest`, etc.) behind the existing `ProcessRunner`/`FileSystemPort` ports, plus manifest-driven variable validation for scaffold prompts.

`textual` is the only third-party dependency. If a stack's real behavior ever needs another one (an SDK client, a templating engine), add it deliberately and put it behind a port, the same way `ProcessRunner`/`FileSystemPort` keep the domain free of concrete tools.

