# 1. A project declares its own commands, and the toolbox reads them

> **Status: ACCEPTED (2026-09-05).** Capability at `capabilities/scripts.py`, reader at `domain/script_config.py`.

## Context

Build already ran the workflows a **stack's** script repository declares. What that did not
cover is the commands a *particular project* has — build this installer, sign that payload,
tag a release — which are this repository's, not a stack's. Two systems with a menu of
commands each, and no reason for either to learn the other's.

## Decision

**A project carrying its own `dti.script.json` has its commands read out of it, and run in
it.** `domain/script_config.py` already said a command runs where its config lives; this
makes that true.

- **The document is the contract; whatever wrote it is not.** A sibling PowerShell toolkit
  emits one, and that is what this was built for and deliberately not what it depends on. A
  project whose commands are npm scripts or a Makefile declares them the same way. Nothing
  in `capabilities/scripts.py` mentions PowerShell.
- **The run is `templates/scripts.py: run_action`**, the same function Build and Components
  use. Reused rather than reimplemented because the valuable parts are the ones easy to
  leave out: answers checked against the document's own rules, tools looked for before
  anything runs, and a stopped run unwinding to the subprocess.
- **Sections are a menu**, from the document's own grouping. Fifty cards in one grid is a
  list to scroll rather than a choice to make.
- **The project comes from `DTI_PROJECT_ROOT`, then the working directory** — the toolbox
  may be started from its own checkout while driving another tree.
- **A `path` argument gets a picker**, declared as a manifest type rather than a string
  convention, because the difference is what the form can offer.

## Consequences

- The four identity keys matter twice: a document with `config` but no identity lists every
  command and then refuses to run any, because the directory is not a project.
- `Ui` grew `choose_script_section`; `ScriptAction` grew a `description`, without which ten
  commands all read "Runs the git workflow".
- A new menu step meant a new `TRAIL_STEPS` entry, and forgetting it killed the capability
  silently — `docs/pitfalls.md` 1.1.

## Alternatives rejected

- **Shell out per command to ask what it accepts.** Forty interpreter starts before the
  first card is drawn.
- **Build each command line from the argument types.** That puts one toolkit's
  parameter-binding rules inside a program that also drives Flutter and React.
- **Fold project commands into Build.** Build is a stack's workflows; one action reachable
  two ways is two breadcrumbs and two places to look for the run you started.
