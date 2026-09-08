# 2. The version is one file, and the gate is one command

> **Status: ACCEPTED (2026-09-05).** `VERSION` at the repository root, read by `presentation/branding.py`. Gate at `company_tui/check.py`, run as `python -m company_tui check`.

## 1. Context

Two habits from the PowerShell toolkit this app is taking over from, adopted here because both answer failures this repository has actually had.

The version was a literal in `branding.py` - `APP_VERSION = "v0.0.0+1"` - and also a number written into `CLAUDE.md`'s first paragraph. Two copies of one fact, and the one on screen is the one that goes stale.

The definition of done listed three commands to run by hand. Nothing ran them together, and one of the three had been passing over an empty test directory for as long as `tests/` had been gitignored.

## 2. Decision

### 2.1 `VERSION` holds `x.y.z+n`, and everything derives from it

One line, at the repository root, the way the PowerShell toolkit and the desktop product both do it. A release rewrites that file and nothing else.

`branding.py` reads it and **falls back rather than raising**. The version decorates a header; an app that refuses to start because it cannot find a text file is worse than one whose title bar is vague, and an installed wheel has no repository around it.

The build number `+n` rises globally across version names, not per version - the rule the installer depends on in the product this tooling builds, kept here so the two do not have to be reasoned about differently.

`domain/identity.DEFAULT_VERSION` is deliberately **not** this. That is the version stamped into a project this toolbox *creates*, which has nothing to do with the toolbox's own.

### 2.2 `check` is the gate, and a skip is reported

`python -m company_tui check` runs the definition of done: the tests, `list`, and `doctor`. It can install itself as a pre-push hook.

Two rules carried over from the toolkit's `check-all`:

- **A skip is reported, never omitted.** A run must never look like it verified something it did not.
- **A check that stops checking is a failure.** `unittest discover` exits 0 when it finds nothing, which is precisely how this repository shipped with no tests while its own documentation cited two test files by name. An empty discovery is `FAIL`.

Each check is a subprocess of `sys.executable`, so the venv running the gate is the venv the checks run in.

## 3. Consequences

- `CLAUDE.md` no longer states a version number; it points at `VERSION`.
- The pre-push hook is opt-in (`--install-hook`), because installing a hook in somebody's checkout without asking is a surprise.
- There is still no release command here. Bumping `VERSION` and tagging is manual, and that is the next thing worth taking from the toolkit.

## 4. Alternatives rejected

**Read the version from package metadata (`importlib.metadata`).** Correct for an installed wheel and wrong in a checkout, which is where this is developed - it reports whatever was last `pip install -e`'d, not what the source says now.

**Keep the literal and add a test that it matches `VERSION`.** A test that two copies agree is a way of keeping two copies.
