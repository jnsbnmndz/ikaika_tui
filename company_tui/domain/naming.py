"""Every name this product answers to, in one place.

The toolbox carried one company's name in 108 places - a manifest filename, an
environment variable, a store directory under the user's home, a settings file, a
bundle prefix, a theme, and prose. It is a generic developer toolbox, so the name
is now `Generic` and it is written down once, here, with everything else deriving
from `APP_SLUG`.


WHY THERE ARE OLD NAMES AS WELL

Four of those names are not decoration - they are a wire format, and something
else on the machine already speaks it:

    the manifest filename        written by the PowerShell toolkit, read here
    the project-root variable    set by that toolkit's launcher, read here
    the store directory          holds cloned script repositories and sessions
    the settings filename        a file people have already edited

Renaming them outright would stop every project that has one being recognised,
and would silently move a store somebody's work is in. So each has a *resolver*:
the new name is what gets WRITTEN, and either name is ACCEPTED when reading. A
function rather than an `or` at each call site, because a fallback spelled out
five times is a fallback that will be right in four places.

The old names are a compatibility surface, not a second convention. Nothing new
should be added to the legacy tuples; when they can be dropped, they go together.
"""

import os
from collections.abc import Mapping
from pathlib import Path

APP_SLUG = "generic"
"""Lowercase, filesystem-safe, and the root every other name is built from."""

APP_NAME = "GENERIC"
APP_TITLE = "Generic"
APP_TAGLINE = "Developer Toolbox"
APP_SIGNATURE = "Generic Engineering"

SCRIPT_MANIFEST = f"{APP_SLUG}.script.json"
LEGACY_SCRIPT_MANIFESTS: tuple[str, ...] = ("ikaika.script.json",)

PROJECT_ROOT_VAR = f"{APP_NAME}_PROJECT_ROOT"
LEGACY_PROJECT_ROOT_VARS: tuple[str, ...] = ("IKAIKA_PROJECT_ROOT",)

STORE_DIR_NAME = f".{APP_SLUG}"
LEGACY_STORE_DIR_NAMES: tuple[str, ...] = (".ikaika",)

CONFIG_NAME = f"{APP_SLUG}.toml"
LEGACY_CONFIG_NAMES: tuple[str, ...] = ("ikaika.toml",)

BUNDLE_PREFIX = f"com.{APP_SLUG}"


def manifest_names() -> tuple[str, ...]:
    """Every filename a project's manifest may have, preferred name first."""
    return (SCRIPT_MANIFEST, *LEGACY_SCRIPT_MANIFESTS)


def manifest_in(root: Path) -> Path | None:
    """The manifest this directory actually has, or `None`.

    Preferred name first, so a project carrying both - one written before the
    rename and one after - is read as the new one rather than by directory order.
    """
    for name in manifest_names():
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def manifest_path(root: Path) -> Path:
    """Where a manifest goes, whether or not one is there.

    An existing file keeps its name: rewriting a project's identity should not
    also rename the file it lives in, which would leave the old one behind
    holding a stale copy of the same four keys.
    """
    return manifest_in(root) or (root / SCRIPT_MANIFEST)


def config_names() -> tuple[str, ...]:
    return (CONFIG_NAME, *LEGACY_CONFIG_NAMES)


def project_root_from_env(environ: Mapping[str, str] | None = None) -> str:
    """What a launcher said the project is, or `""`.

    The new variable wins where both are set, so a launcher that sets both while
    the two repositories move at their own pace is not ambiguous.
    """
    source = os.environ if environ is None else environ
    for name in (PROJECT_ROOT_VAR, *LEGACY_PROJECT_ROOT_VARS):
        value = str(source.get(name, "")).strip()
        if value:
            return value
    return ""


def store_dir(home: Path | None = None) -> Path:
    """Where this toolbox keeps what it has cloned and remembered.

    An existing store is used where it is. Preferring the new name and creating
    it would leave every cloned script repository and every remembered tab
    behind a directory nothing reads any more - which looks exactly like the
    toolbox having lost them.
    """
    base = Path.home() if home is None else home
    preferred = base / STORE_DIR_NAME
    if preferred.is_dir():
        return preferred
    for name in LEGACY_STORE_DIR_NAMES:
        legacy = base / name
        if legacy.is_dir():
            return legacy
    return preferred
