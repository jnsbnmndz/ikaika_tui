"""Every name this product answers to, in one place."""

import os
from collections.abc import Mapping
from pathlib import Path

APP_SLUG = "dti"
"""Lowercase, filesystem-safe, and the root every other name is built from."""

APP_NAME = "DTI"
APP_TITLE = "Developer Toolbox Inventory"
APP_TAGLINE = "Developer Toolbox"
APP_SIGNATURE = "Developer Toolbox Inventory"

SCRIPT_MANIFEST = f"{APP_SLUG}.script.json"
LEGACY_SCRIPT_MANIFESTS: tuple[str, ...] = ("generic.script.json", "ikaika.script.json")

PROJECT_ROOT_VAR = f"{APP_NAME}_PROJECT_ROOT"
LEGACY_PROJECT_ROOT_VARS: tuple[str, ...] = (
    "GENERIC_PROJECT_ROOT",
    "IKAIKA_PROJECT_ROOT",
)

STORE_DIR_NAME = f".{APP_SLUG}"
LEGACY_STORE_DIR_NAMES: tuple[str, ...] = (".generic", ".ikaika")

CONFIG_NAME = f"{APP_SLUG}.toml"
LEGACY_CONFIG_NAMES: tuple[str, ...] = ("generic.toml", "ikaika.toml")

BUNDLE_PREFIX = f"com.{APP_SLUG}"


def manifest_names() -> tuple[str, ...]:
    """Every filename a project's manifest may have, preferred name first."""
    return (SCRIPT_MANIFEST, *LEGACY_SCRIPT_MANIFESTS)


def manifest_in(root: Path) -> Path | None:
    """The manifest this directory actually has, or `None`."""
    for name in manifest_names():
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def manifest_path(root: Path) -> Path:
    """Where a manifest goes, whether or not one is there."""
    return manifest_in(root) or (root / SCRIPT_MANIFEST)


def config_names() -> tuple[str, ...]:
    return (CONFIG_NAME, *LEGACY_CONFIG_NAMES)


def project_root_from_env(environ: Mapping[str, str] | None = None) -> str:
    """What a launcher said the project is, or `""`."""
    source = os.environ if environ is None else environ
    for name in (PROJECT_ROOT_VAR, *LEGACY_PROJECT_ROOT_VARS):
        value = str(source.get(name, "")).strip()
        if value:
            return value
    return ""


def store_dir(home: Path | None = None) -> Path:
    """Where this toolbox keeps what it has cloned and remembered."""
    base = Path.home() if home is None else home
    preferred = base / STORE_DIR_NAME
    if preferred.is_dir():
        return preferred
    for name in LEGACY_STORE_DIR_NAMES:
        legacy = base / name
        if legacy.is_dir():
            return legacy
    return preferred
