# 1. A project declares its own commands, and the toolbox reads them

> **Status: ACCEPTED (2026-09-05).** Landed in v0.1.0+2. Capability at `capabilities/scripts.py`, reader at `domain/script_config.py`. The PowerShell toolkit's matching decision is its ADR 0015.

## 1. Context

`ScriptsCapability` said "Project scripts are not configured yet" and did nothing. Meanwhile Build already ran the workflows a **stack's** script repository declares - cloned into `~/.ikaika/scripts`, shared by every project on the machine, described by an `ikaika.script.json`.

What that did not cover is the commands a *particular project* has: build this installer, sign that payload, pull updates, tag a release. Those are not a stack's, they are this repository's, and there are dozens of them behind a PowerShell dispatcher that already knew every one.

Two systems each with a menu of commands, and no reason for either to learn the other's.

## 2. Decision

**A project carrying its own `ikaika.script.json` has its commands read out of it, and run in it.**

`domain/script_config.py` already said as much: *a command runs where its config lives, so a project carrying a `config` of its own runs in the project.* This makes that sentence true.

### 2.1 The document is the contract; whatever wrote it is not

The IKAIKA PowerShell toolkit emits one describing every command it can dispatch, and that is what this was built for. It is deliberately **not** what it depends on. A project whose commands are npm scripts, a Makefile, or a shell script per task declares them the same way and arrives at the same menus.

Nothing in `capabilities/scripts.py` mentions PowerShell.

### 2.2 The run is `templates/scripts.py: run_action`, not a second copy

The same function Build and Components go through. An action with no template and no path - which every project command is - skips the staging half and runs what the config named.

Reused rather than reimplemented because the valuable parts are the ones easy to leave out: answers checked against the rules the document itself declared, the tools its commands need looked for on the machine *before* anything runs, `${...}` expanded against one map, and a stopped run unwinding to the subprocess rather than orphaning it.

### 2.3 Sections are a menu, because the document already grouped them

`config` holds a section per kind of work and this repository's own manifest declares six. Fifty cards in one grid is a list to scroll rather than a choice to make, and the grouping is the author's, not one invented here - a repository that renames a section moves its own menu.

### 2.4 The project comes from `IKAIKA_PROJECT_ROOT`, then the working directory

The toolbox may be started from its own checkout while driving another tree. A variable rather than an argument, so it survives whatever the app does with its own command line.

### 2.5 A `path` argument gets a picker

Added as a manifest type rather than a string convention, because the difference is what the form can offer. A text box asking for a directory is a box somebody has to remember the answer to. A declared set of paths is still offered as the set - a choice beats a picker when the answers are known.

## 3. Consequences

- The four identity keys matter twice over. A document with `config` and no `version`/`name`/`description`/`title` parses, lists every command, and then refuses to run any of them, because `require_project` says the directory they are aimed at is not a project.
- `Ui` grew `choose_script_section`, implemented by both consoles.
- `ScriptAction` grew a `description`, read from the document. Without it ten commands in one section all read "Runs the git workflow" - true of each, useful about none.
- A new menu step meant a new entry in `TRAIL_STEPS`, and forgetting it killed the capability silently. See `docs/pitfalls.md` 1.1.

## 4. Alternatives rejected

**Have the app shell out per command to ask what it accepts.** Forty commands is forty interpreter starts before the first card is drawn.

**Let the app build each command line from the argument types.** That puts one toolkit's parameter-binding rules inside a cross-platform Python program that also drives Flutter and React projects - rules it cannot test and has no business knowing. The document declares the whole command line instead, with each argument as a `${...}` reference.

**Fold project commands into Build.** Build is a stack's workflows against a project. These are a project's own, and one action reachable two ways is one action with two breadcrumbs, two tabs and two places to look for the run you started.

## 5. What would change this

A project needing its commands *discovered* rather than declared - at which point the reader stays and something else writes the document, which is already how it works.
