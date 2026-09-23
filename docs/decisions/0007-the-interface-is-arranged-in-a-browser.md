# 7. The settings are edited in a browser, and the interface is designed in one

> **Status: ACCEPTED (2026-09-18), amended 2026-09-19** to edit the whole settings
> document, to hold named themes, to let the project being worked on override the
> settings, and to edit that project's own commands. Layout `domain/layout.py`, page
> `infrastructure/builder_page.py`, server `infrastructure/builder.py`, capability
> `capabilities/builder.py`.

## Context

The interface's appearance was constants: `APP_THEME` in `branding.py`, four sizes in
`window_shape.py`, `CARDS_PER_ROW` in `screens.py`, and the menu's order fixed by the order
things are registered in `bootstrap.py`. Changing any of them meant editing Python, which
puts them out of reach of the people who run this and nowhere near the people who ask for
"could the cards be two across".

## Decision

### It edits the settings document, and defines nothing

The page is an editor for the document `domain/settings_document.py` already writes
and reads - the one App Setup exports and imports. Every field it offers goes back
through `read_document`, is validated by the same code the TUI's own forms are, and
is saved through `ConfigPort` like every other setting.

That is the whole reason a second editor is safe. Two editors for one file is a real
hazard: they drift in what they accept, in what they call things, and in which of
them is right. Two *views* over one document, one reader and one writer, cannot.

Add, update and delete fall out of it rather than being built: the document already
replaces `templates`, `scripts` and `script_checks` wholesale when they are present,
so a key that is not in what the page sent is a key that is gone. Nothing was added
to express deletion.

### What a builder can honestly be built over

**Not the screens.** They are hand-written `compose()` methods and CSS with a documented
reason behind most widgets, and a drag-and-drop editor over them would have to be a code
generator — writing files nobody should then hand-edit, and losing every reason recorded in
this repository the first time it regenerated one.

What *is* arrangement rather than behaviour is the palette, the window, and the menu grid.
That is the whole of what `domain/layout.py` holds. A tool that claims more than it can do
is worse than one that claims less.

Everything else the page offers - the workspace, the template packs, the script
repositories, the update feed, the experimental flags - is settings, and was already
settings. The builder is a better surface for them, not a new answer about them.

### Themes are named, and there is always one

A single palette could be recoloured but not kept, so trying a dark variant meant losing
the one you had. `Layout.themes` is a map of name to palette and `Layout.theme` says which
is in use, which is what makes add, duplicate, rename and delete mean anything.

Two floors: there is always at least one theme, and the name in `theme` always points at
one that exists. `Layout.palette` falls back rather than raising - a theme can be deleted
out from under the name pointing at it, and an interface with no colours is not an answer to
anything. A name is spelled like the settings-file key it becomes.

A document carrying a bare `palette` and no `themes` reads as the default theme's colours,
so a file written before there was more than one still works.

### The project being worked on wins, and it is one file winning outright

The toolbox may be started from its own checkout while driving another tree, so the
directory it happens to be in was never the right answer for *which project* - it already
was not for finding commands. Now it is not for settings either: `driven`, then `project`,
then `user`, and the **first one that exists wins outright**. Never merged, because two
files half-answering a question is a preference written where nothing reads it, and that is
a question that keeps being asked.

A repository can therefore pin its own theme, its own menu, its own template sources and its
own experimental flags for anyone who drives it. That is not new trust: driving a project
already means running the commands it declares, and a `dti.toml` cannot do anything a
`dti.script.json` could not already do.

`ConfigPort.follow` is how the toolbox is told which project that is, and `scopes()` is why
a form only offers `driven` while there is one - a "save to" naming a file that does not
apply is a control that lies. `naming.project_root()` is the single answer to which tree it
is, because the settings, the commands and the menus all have to agree.

### The project's commands are edited in place, and only the parts it offers

`domain/commands.py` reads the same `dti.script.json` the runner reads, and writes back
**only** `description`, `command-after-success`, `interactive` and `view`. Everything else on
an action - its `args`, its `template`, its `path`, its `messages`, whatever a later version
of that document grew - is read and put back untouched, at the file's own indent, because
this is somebody else's contract file and the toolbox owns only what it offers to edit.

Telling an action from a group of them is `script_config.ACTION_MARKERS` and nothing else.
Two answers to what an action is would be two menus that disagree.

**A rename moves what was there rather than building a new one.** That is what `Command.was`
is for: without it a rename is a delete and an add, and the template and the arguments go
with it, silently. And a rename that orphans the action's own `${<name>.args.<flag>}`
references **says so** - an unanswered reference is left in place rather than blanked, so
what fails is the run, three menus later, with the text still in it.

The builder will not *create* a manifest for a project that has none. What makes a directory
one of these projects is `ProjectFinalizer`; a page that wrote one would be deciding that it
is one.

### Every default is what the code held

`plan_from(Window()) == DEFAULT_PLAN`, and `theme_from(Palette()) == APP_THEME` colour for
colour, both under test. So a toolbox nobody has arranged draws exactly what it drew before
this existed, and the settings file says nothing about the arrangement until somebody
arranges something.

### It is a browser, and only for this

Dragging a grid into shape with a mouse is something a browser does well and a terminal
does badly, and this is a design-time tool: it runs once while somebody is deciding, not
while they are working, so the context switch buys something. It is the **only** capability
whose surface is not this interface, and that is a line worth keeping — the next feature
that wants a web page should have to make this argument again.

Everything about the server follows from it being open only for that run:

- `127.0.0.1` on an ephemeral port, so nothing on the network reaches it.
- **A single-use token on every request.** Localhost is not a boundary — any program on this
  machine can reach a loopback port, and any page in the browser can POST to one. Without
  the right token every path answers 404, which is also what a wrong token gets: a 403
  confirms the path.
- **Assets from a dict, never the filesystem**, so there is no path to traverse. The page is
  program text in `builder_page.py` for the same reason `handover.py`'s script is: it ships
  with the code rather than as a file the frozen build has to be told to carry.
- **A refused body is read away before the refusal is sent** (`docs/pitfalls.md` 10.1).
- **The server writes nothing.** It hands back settings and the capability saves them
  through `ConfigPort`, so there is still one place that writes settings.

### The settings apply now; the look applies next launch

Everything the page edits is saved to the settings file at once, and `FileConfig` forgets
what it read on save, so a template source or an experimental flag is in force immediately.
The palette, the window and the grid are taken up when the app starts, and the browser's
own preview is where somebody sees their changes as they make them. One rule rather than
three: the alternative was a palette that applied live beside a window that could not, which
is a control that half lies. `TuiConsole` reads the layout at mount for the same reason it
reads the window plan there — an interface that rearranged itself under somebody using it is
worse than one that waits.

### Off the menu is not gone

`hidden` leaves a card off the grid. `registry.get` still finds it, so `--start` naming a
hidden capability opens it, and `registry.every()` still lists it so the builder can offer it
to be dragged back. **Hiding all of them is refused** — a menu with no cards is an app with
no way in, and the file saying so would have to be edited by hand to escape.

### Reordering is allowed, and it is the one rule this bends

`CLAUDE.md` says a new capability is appended rather than inserted, "or every number people
have learned moves". That is a rule about what *this repository* may do to somebody's menu.
Somebody rearranging their own menu is choosing to move those numbers, and the numbers
follow the order they leave it in. Registration order remains what happens when nobody has
said otherwise, which is the case this repository controls.

### An unreadable value is reported, never guessed

A colour that is not a colour reaches Textual as a theme it refuses, and an app with no
theme is an unstyled one — so `read_layout` checks `#rgb`/`#rrggbb` itself, keeps what was
already set, and names what it would not take. The same for sizes outside 320-10000, a grid
wider than six, and a floor above the size it is the floor for. Everything skipped is
printed, in the terminal and on the page.

## Alternatives rejected

- **Generating screen code from a canvas.** See above: it would delete the reasoning that is
  the most valuable thing in `presentation/`.
- **A Textual screen with mouse dragging.** Possible, and worse at the one job the feature
  exists for. A grid of draggable cards with live colour is what browsers are for.
- **Serving the page from files under `company_tui/builder/`.** A packaging problem for the
  frozen build, and a filesystem for a request to walk. Program text has neither.
- **Binding to `0.0.0.0` "so you can arrange it from your laptop".** A settings editor for
  this machine, reachable from the network.
- **No token, because it is localhost.** Every process on the machine, and every page in the
  browser, can reach a loopback port.
- **A separate `dti.layout.json`.** A second store, a second scope question, and a second
  thing to carry between machines. `[layout]` in the settings file already has all three.
- **The page defining its own fields.** Then there are two answers to what a setting is,
  and the day they disagree is the day somebody's file is quietly wrong.
- **A `delete` verb on the wire.** The document already says what exists by listing it.
- **One palette that is edited in place.** You can recolour it but not keep what you had,
  so every experiment costs you the thing you were comparing against.
- **Merging the three settings files.** Then a value can come from anywhere, and "why is it
  that" has three answers.
- **A rename as a delete and an add.** It loses everything the builder does not edit, and it
  loses it quietly.
- **Editing `args` here.** Arguments carry the document's own declared grammar (`rules`), and
  a form that wrote them without that grammar would write manifests the runner refuses. They
  are shown as kept and left alone until the page can read `rules` too.
- **Creating a manifest for a project that has none.** That decides a directory is one of
  these projects, which is a scaffold's decision.
- **Applying changes live.** Some of it can and some of it cannot, and a builder where half
  the controls take effect now is harder to explain than one where none of them do.

## What would change this

Wanting to arrange something that genuinely is per-screen — which pane of the run panel is
wider, say. That is real configuration rather than generated code, and it would want the
layout document to grow a section per screen rather than the builder to grow a canvas.
