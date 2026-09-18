# Developer Toolbox Inventory

A scalable Python terminal application for development workflows. It scaffolds projects,
builds and deploys them, runs a project's own commands, and maintains itself.

The version is not written here — it lives in `VERSION` at the repository root, one line,
`x.y.z+n`, read by `presentation/branding.py`. A version quoted in a README is one that
goes stale. Every name the product answers to lives in `domain/naming.py`, derived from
`APP_SLUG`.

`python -m company_tui` opens an interactive [Textual](https://textual.textualize.io/) UI:
card menus, a themed frame, tabbed run panels. `list` and `doctor` stay plain, synchronous,
scriptable stdout with no terminal takeover.

**`CLAUDE.md` is the guide for working in this repository.** `docs/decisions/` is why the
architecture is what it is, and `docs/pitfalls.md` is what has actually gone wrong.

## Run

Python 3.11 or newer.

```sh
python -m company_tui                  # interactive Textual UI
python -m company_tui --start scripts  # open straight on a capability
python -m company_tui list             # plain stdout, scriptable
python -m company_tui doctor           # plain stdout, scriptable
python -m company_tui check            # the gate: tests, list and doctor
python -m company_tui --version
```

```sh
python -m pip install -e .   # installs two names for one entry point: dti, company
python -m unittest discover
python -m company_tui check --install-hook   # as a pre-push hook
```

An installed copy is started by typing `dti` in any new terminal — the installer puts its
directory on PATH.

## Structure

```text
company_tui/
├── application/      orchestration, capability and template-pack registries
├── capabilities/     independently executable features (scaffold, build, deploy, scripts,
│                     settings, doctor, app_setup, updates, advanced)
├── domain/           stable models and interfaces
├── infrastructure/   operating system and external tool adapters
├── presentation/     Ui protocol, PlainConsole (stdout), TuiConsole (Textual)
├── templates/        one versioned template pack per stack
├── bootstrap.py      dependency composition
└── cli.py            command-line entry point
```

Dependencies point inward: presentation and infrastructure implement the edges, application
coordinates, and the domain stays independent of concrete tools. Every interactive step is
`async` — `Application.run()`, `Capability.execute()`, `TemplatePack.scaffold()`/`.build()`
— which is what lets one capability run unchanged against either console.

## The interface

- `presentation/branding.py` holds the theme, tagline and version; `presentation/chrome.py`
  is the frame, header and footer every screen is composed inside.
- **Every key hint is also a button.** A hint reads its label back into the key it sends, so
  the mouse reaches everywhere the keyboard does and a hint cannot drift from what it does.
- **Every context has its own tabs**, numbered from one, and a tab outlives its run — the
  output, the time it ran, and the form still holding what you typed. `Ctrl+B` lists every
  run there is. Esc is always one step back; from a run panel it leaves the run going.
- **No emoji**, ever — terminals disagree about their width, which shifts every column
  after them. Line art from `presentation/icons.py` instead, enforced by
  `tests/test_glyphs.py`.

## Interactive lists (experimental, off)

A command's output is dead text, so anything browse-shaped — walking folders, picking from
results — means re-running it with a different argument each time and holding the last
listing in your head. A command can instead hand over a list of rows and be told which one
was picked, without exiting.

**Two things must both say yes**, and either alone changes nothing:

1. `interactive_lists` in **[09] Advanced**, off by default.
2. `"interactive": true` on that command in its `dti.script.json`.

With both, the child gets `DTI_INTERACTIVE=1` and an stdin pipe. It may then print:

```
@dti:rows {"title":"Project Files","hint":"Enter opens",
           "rows":[{"id":"1","label":"00_BIM","kind":"folder"},
                   {"id":"10","label":"Deck.pptx","kind":"file","detail":"v1  97 MB"}]}
```

The toolbox draws a real list — arrow keys, Enter — and writes back one line:

```
@dti:pick 10
```

Then it keeps reading: the command prints another block, or `@dti:end` to go back to plain
streaming. Esc answers with nothing and stops the command.

Any line that is not understood — an unknown verb, broken JSON, a row with no `id` — is
printed as ordinary output rather than breaking the view, so a command written for a later
version cannot break an older toolbox. `id` is opaque and echoed back verbatim; `kind` and
`detail` are presentation only.

### A list can answer itself

Some questions have a right answer when nobody is at the keyboard — retry or give up,
overwrite or skip, keep going or stop. The command says so on the same payload:

```
@dti:rows {"rows":[{"id":"retry","label":"Try again"},{"id":"stop","label":"Stop"}],
           "timeout":20,"default":"stop"}
```

The hint line counts down and names the winner (`20s → Stop`), and on expiry the toolbox
writes back `@dti:pick stop` like any other answer. **Any interaction ends the countdown for
good** — an arrow key, a click, the pointer moving onto another row — because a choice taken
away part-way through reading it is worse than never offering to answer it.

`timeout` without a `default` naming one of these rows is **ignored entirely and the list
waits**. Never row zero: silently picking the first one is how somebody loses what they
meant to keep.

This is a **third** switch, `timed_prompts`, also in **[09] Advanced** and also off. With it
off — or on an older toolbox, or in a plain terminal — the list renders and waits exactly as
it does now, and the extra fields are dropped before the screen ever sees them. A command is
never told whether its countdown is live, so nothing can be written to depend on one
(`docs/decisions/0005`).

### A command that is a place rather than a run

Some commands are not "configure, run, read output" — they are somewhere you move around
in. A remote file store, a bucket, a package registry, a database's tables and rows, a log
archive, a branch's history: any navigable hierarchy. A script entry can say so, and the
toolbox opens a **two-pane browser** instead of the configuration form and the terminal:

```json
{ "view": "browser" }
```

Breadcrumb across the top, tree on the left, a table on the right whose columns the command
declares, an action bar showing only what is available right now, and a status line. No
terminal pane, no Run button. A **fourth** switch, `browser_view` in **[09] Advanced**, off
by default, and the manifest has to say `"view": "browser"` as well.

The command owns all of it. The toolbox fetches nothing and knows nothing about what is
being browsed — it draws the rows a command sends and reports what the user did:

```
@dti:view    {"columns":[{"key":"name","label":"Name","grow":true},
                         {"key":"size","label":"Size","width":10,"align":"right"}],
              "tree":[{"id":"root","label":"Root","parent":null}]}
@dti:rows    {"breadcrumb":["Root","Reports","2026"],
              "rows":[{"id":"r-1","cells":{"name":"march","size":"4.2 MB"},"kind":"leaf"}],
              "actions":[{"id":"add","label":"Add","key":"a"},
                         {"id":"remove","label":"Remove","key":"r","danger":true}]}
@dti:status  any one-line message the command wants under the list
@dti:end
```

and reads back one line per thing the user did:

```
@dti:open r-1                 a row was entered
@dti:action remove r-1        an action was run, on that row
@dti:action add               an action was run on where the user is, not on a row
```

A few rules make this work for a command listing database tables as well as one listing
files:

- **Actions are per-listing, never hardcoded.** The bar shows exactly what the last
  `@dti:rows` declared and nothing else, so a command that varies its actions by location
  — permissions, state, node type — gets that for free, and the toolbox never learns why.
- **`danger: true` is styling only.** The confirmation stays with the command, sent as an
  ordinary `@dti:rows` pick-list (with the countdown above, where `timed_prompts` is on) and
  shown as a modal over the browser. The toolbox never invents its own "are you sure": only
  the command knows what is about to happen.
- **A listing carrying `breadcrumb` is the pane; one without it is a question over it.** The
  key being present is what decides, so a browser at its own root is still a pane.
- **Cells are strings.** A command already decides that 4402816 bytes reads as "4.2 MB".
- **One text-input verb, used sparingly.** `@dti:ask {"prompt":"...","value":""}` for a
  value nothing can list — a name for a thing that does not exist yet — answered with
  `@dti:answer <text>`, or `@dti:answer` alone for a cancel. Everything else here is a row
  or an action.
- **`@dti:rows` blocks until the user acts**, so anything the command wants shown beside it
  goes first. A status set that way stays up until it is replaced.

With `browser_view` off — or on an older toolbox — a `"view": "browser"` command still runs
as an ordinary script: the form and terminal appear, `@dti:view`, `@dti:status` and
`@dti:ask` are printed as text, and `@dti:rows` is the pick-list it always was (a row with
only `cells` is labelled by its first cell so it stays legible). **Read the verb of the line
you are sent** — `@dti:pick`, `@dti:open` or `@dti:action` — and one command works on both.
Nothing else tells it which surface it got, which is what stops a command being written to
require the browser (`docs/decisions/0006`).

The switch is an environment variable rather than a flag so **the same command run in a
plain terminal sees nothing set and prints its ordinary human-readable output**. Both
surfaces stay clean.

Not a pty: no cursor control, no full-screen apps. It is a list protocol.

## Building and releasing

One entry point, and GitHub Actions calls the same file rather than restating the steps in
YAML — a workflow with its own list of steps is a second, silently diverging answer to what
a release is.

```powershell
.\script.ps1                              # commands are discovered from scripts\
.\script.ps1 <command> -Help
.\script.ps1 setup-dev-env -Build -Lint   # make a machine able to build
.\script.ps1 check-all                    # the gate; -InstallHook for pre-push
.\script.ps1 setup-signing                # release and debug certificates
.\script.ps1 bump-version -Bump patch     # rewrite VERSION, commit, tag
.\script.ps1 build-app -Sign              # freeze with PyInstaller
.\script.ps1 benchmark                    # time each -Optimize level, print a matrix
.\script.ps1 build-installer -Sign        # wrap it in NSIS
```

### The build number comes from the tags

It rises **globally**, across version names: `1.1.9+7` is followed by `1.2.0+8`, never
`1.2.0+1`. An installer compares that number, so a reset makes an upgrade look older than
what is installed. A number a tag has claimed is never handed out twice.

So a release has to be **tagged**. `bump-version` commits and tags but pushes nothing —
publishing is a decision, and a build tool that pushes on your behalf is one nobody can
rehearse.

### `-released` is what makes a build official

    v1.2.0+8              a debug build, published as a prerelease
    v1.2.0+8-released     the official release

One version can carry both, sharing one build number, because the number belongs to the
source. The suffix stays **last**: `Release.official` asks what a tag ends with, so
`v1.2.0-released+8` would read as a debug build.

### The release workflow publishes nothing by default

Dispatched by hand, with `tag` — the one input that decides whether anything leaves the
runner — **off**. A default run is a rehearsal: the gate, a real signed build, a real
installer kept as an artifact, and nothing tagged, pushed or published.

| Input | Default | What it does |
|---|---|---|
| `bump` | `patch` | which part to raise; `keep` takes a build number and leaves the name |
| `released` | off | adds `-released` and publishes as latest rather than a prerelease |
| `sign` | on | sign the artifacts; needs the three signing secrets |
| `tag` | **off** | commit, tag, push, publish |
| `installer` | on | also wrap the frozen app in the NSIS installer |
| `clean` | off | clear PyInstaller's cache first |

### Signing

Two certificates — a release identity and a debug one, so a test build is not an Unknown
Publisher either, without spending the trust the real signature has built.

| What | Where | Committed? |
|---|---|---|
| The private keys | `certs/*.pfx` | **no** |
| The password and both share links | `.dti_configs/signing.env` | **no** |
| Their checksums | `.dti_configs/*.pfx.sha256` | yes, deliberately |
| The publisher subject | `.dti_configs/share.env` | yes |

The checksums are the point: a `.pfx` arrives over a link from a machine nobody here
controls, and a same-named file is not the same file. The links are secrets because a
share link *is* the capability to fetch the file, and a committed link cannot be rotated —
see `docs/decisions/0003`. CI reads `DTI_CERT_PASSWORD`, `DTI_CERT_SHARE_URL` and
`DTI_DEBUG_CERT_SHARE_URL`. A missing certificate does not fail the build; it says the
artifacts are unsigned and carries on.

### Startup, and the build variants

`build-app` takes two levers, both exposed as release-workflow inputs:

```powershell
.\script.ps1 build-app -Optimize 2      # bytecode: 1 drops asserts, 2 also drops docstrings
.\script.ps1 build-app -Python 3.14     # freeze against a chosen CPython, fetched by uv
```

They exist to be **measured**, not assumed. `.\script.ps1 benchmark` builds each variant and
times the commands that start and exit, and `-UpdateReadme` writes the result into the
table below — so these numbers come from a real run rather than from someone's memory.

<!-- benchmark:start -->
`dti 0.3.0+26` on CPython 3.12.10, a GitHub runner, fastest of 9 interleaved rounds, in milliseconds.

| Build | Size MB | --version | list | doctor |
|---|---|---|---|---|
| `-O0` | 28.1 | 166 | 213 | 282 |

_Generated by `.\script.ps1 benchmark -UpdateReadme`; do not edit by hand._
<!-- benchmark:end -->

What actually mattered was neither lever. `cli.py` pulled `bootstrap` and `branding` at
module level, and `branding` imports `textual` for the theme — so `--version`, `list` and
`doctor` each paid ~700 ms to load a terminal framework none of them use, against a
documented promise that they stay fast and pipeable. Deferring those imports took frozen
`--version` from **863 ms to 251 ms**. Measure before reaching for a build flag.

### The installer

NSIS, per-user under `%LOCALAPPDATA%\Programs`, so it needs no administrator prompt. An
upgrade runs the old uninstaller first, because copying over a PyInstaller folder leaves
whatever the new build no longer ships on the import path.

**A debug build installs beside the release, not over it** — everything identifying an
install derives from `INSTALL_SLUG`:

| | release | debug |
|---|---|---|
| Directory | `…\Programs\dti` | `…\Programs\dti-debug` |
| Add/Remove entry | Developer Toolbox Inventory | … **(debug)** |
| Command | `dti` | `dti-debug` |

That is not tidiness: `UNINSTALL_KEY` was shared once, so installing a debug build ran the
*release* build's uninstaller and installed over its directory. The debug build also gets
its own executable name, because two `dti.exe` on PATH makes the command whichever
directory comes first — invisibly.

The store under `~/.dti` is **shared** between them, which is one reason no uninstaller
removes it; the other is that it holds work nobody should delete to tidy up.

**The PATH edit is not done in NSIS.** `NSIS_MAX_STRLEN` is 1024 and `ReadRegStr`
truncates *silently* at it — writing that back is the well-known way an installer destroys
somebody's PATH, and this machine's was already past the limit. `scripts/lib/path-entry.ps1`
does it through .NET, User scope only.

### Updating itself

The app asks the release feed once at launch and says nothing unless the answer is useful.
If there is a newer build it downloads the installer and the header grows a badge —
`▲ 0.0.2+4 ready · Ctrl+U`. Pressing it asks once, shows what it is doing, closes the
toolbox and hands over.

The handover is the whole feature. The installer runs the old uninstaller and then
`RMDir /r` over the directory holding the running `dti.exe`, which Windows will not delete.
So it is started by a **third** process that waits for this one to exit:

```powershell
powershell -ExecutionPolicy Bypass -File <script> -WaitPid <pid> -Installer <path>
```

A `.ps1` written to `%TEMP%` at runtime, so paths travel as arguments rather than as
program text, and it logs beside itself — removed on success, kept on failure. Started with
`CREATE_NO_WINDOW`, **never** `DETACHED_PROCESS`: detached means no console, and
`powershell.exe` is a console application, so it exits 0 having run nothing. Windows
PowerShell 5.1 rather than `pwsh`, the one place here that cannot assume a developer's
machine. `docs/decisions/0004`, and `docs/pitfalls.md` 6.1 and 6.4.

**An update has a line.** A debug installer cannot update a release install — it installs
beside it — so one is never offered to the other, whatever the channel says. The build
reads its line off the command it runs under.

It is on out of the box; `[updates] check_on_launch = false` stops the launch check, and
clearing the repository in Advanced stops both halves. **Check for Updates** is the card
that reports everything properly, and it can also run an installer you point it at, which
is how a build is tested before it is published.

### Release notes

`POST /releases/generate-notes` returns the changelog GitHub builds from the commits and
pull requests since the last release, and the workflow composes the body itself: the four
lines that matter to somebody installing — version, whether it is signed, where it installs
— then a rule, then the generated part.

Composed here rather than by passing `--generate-notes` to `gh release create`, because
that flag generates the title *and* body and what happens to a `--notes` given alongside it
is undocumented. A failure to generate is not a failure to release: the body falls back to
the four lines.

### CI

The **download** caches — pip's and PyInstaller's — never the virtualenv: a restored pip
cache cannot make a run wrong, while a `.venv` carrying an interpreter the runner has since
upgraded fails on a cache *hit* and passes on a miss. Cache paths are asked for
(`pip cache dir`), not written down, and caching is never why a run fails.

`.github/dependabot.yml` opens the pull requests; `.\script.ps1 check-actions` runs weekly
and **fails** when an action has moved on. Both, because a version check whose only output
is a pull request has no way to say it has stopped running. It used to be a third-party
container action, which is exactly how it failed — `docs/pitfalls.md` 8.1.

## Template packs

Each stack under `templates/<stack>/` is two files: `behavior.py`, the editable hooks
(`scaffold_new_project`, `scaffold_controller`, `build`) and the only file meant to change
per stack; and `pack.py`, a thin adapter implementing `TemplatePack`.

`templates/python/` is the reference for writing a tree file by file;
`templates/react_native/` for cloning one — it shallow-clones the structure repository and
deletes the clone's `.git`, previewed and confirmed before anything touches disk.

To add a stack: copy `templates/_skeleton/`, set `STACK_NAME`, fill in the three functions,
register it in `bootstrap.py`, and add line art in `presentation/icons.py`. See CLAUDE.md.

## Growth path

Flutter and React are wired in as "not available yet" placeholders; the next useful slice is
real tooling calls behind the existing ports.

`textual` is the only third-party dependency. If a stack ever needs another, add it
deliberately and put it behind a port.
