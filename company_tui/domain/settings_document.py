"""Settings as a JSON document, for carrying them between machines.

The settings themselves live in TOML, which is the right format for a file
people hand-edit beside a repository. This is a different job: one file holding
everything, moved to another machine, checked into a gist, or kept as a
before-picture of a configuration somebody is about to change. JSON because it
is what every other tool can already read, and because a document that travels
should be one obvious blob rather than a format with a section layout to respect.


IMPORTING IS FORGIVING AND SAYS WHAT IT IGNORED

A document written by a newer version, or hand-edited into something odd, must
not lose the parts that were fine. So every field is read independently, an
unreadable one falls back to its current value, and each one is REPORTED. The
alternative - refusing the whole file over one bad key - means a person with a
typo has no way to get the other twenty settings across.

What is never done is silent partial success. `read_document` hands back the
problems it found alongside the settings, and the capability shows them; a
document that half-applied while reporting "imported" is the outcome this shape
exists to prevent.


THE SCHEMA NUMBER IS WRITTEN AND CHECKED, NOT ENFORCED

A higher number than this code knows is a warning, not a refusal: the fields it
does recognise are still worth having, and refusing would make the export
useless for exactly the case it is for - moving settings onto a machine running
a slightly different build.
"""

from collections.abc import Mapping
from typing import Any

from company_tui.domain.config import (
    DEFAULT_BUNDLE_PREFIX,
    DEFAULT_SCRIPTS_ROOT,
    DEFAULT_WORKSPACE_ROOT,
    Settings,
    TemplateSource,
)
from company_tui.domain.updates import (
    DEFAULT_API_BASE,
    DEFAULT_ASSET_PATTERN,
    UpdateSource,
)

SCHEMA = 1
SCHEMA_KEY = "schema"
KIND_KEY = "kind"
KIND = "generic-toolbox-settings"


def write_document(settings: Settings) -> dict[str, Any]:
    """Everything, including values equal to the defaults.

    Deliberately unlike the TOML writer, which omits defaults to keep a
    hand-edited file quiet. An exported document is a snapshot: a reader cannot
    tell an omitted key from one that was deliberately set to what happens to be
    today's default, and a default that changes between versions would silently
    rewrite the setting this file exists to preserve.
    """
    return {
        SCHEMA_KEY: SCHEMA,
        KIND_KEY: KIND,
        "scaffold": {
            "workspace_root": settings.workspace_root,
            "bundle_prefix": settings.bundle_prefix,
            "scripts_root": settings.scripts_root,
        },
        "templates": {
            key: {"url": source.url, "ref": source.ref}
            for key, source in sorted(settings.templates.items())
        },
        "scripts": {
            key: {"url": source.url, "ref": source.ref}
            for key, source in sorted(settings.scripts.items())
        },
        "script_checks": dict(sorted(settings.script_checks.items())),
        "updates": {
            "repository": settings.updates.repository,
            "api_base": settings.updates.api_base,
            "include_prereleases": settings.updates.include_prereleases,
            "asset_pattern": settings.updates.asset_pattern,
        },
    }


def read_document(
    document: Any, current: Settings
) -> tuple[Settings, tuple[str, ...]]:
    """Reads what it can, keeps `current` for the rest, and reports the gaps.

    `current` rather than the built-in defaults: a document that says nothing
    about a setting is not asking for it to be reset, and importing one written
    before a field existed should not silently clear that field.
    """
    problems: list[str] = []

    if not isinstance(document, Mapping):
        return current, ("that file is not a settings document - expected a JSON object",)

    kind = str(document.get(KIND_KEY, "")).strip()
    if kind and kind != KIND:
        problems.append(f"the document says it is '{kind}', not '{KIND}'")

    schema = document.get(SCHEMA_KEY)
    if isinstance(schema, int) and schema > SCHEMA:
        problems.append(
            f"written for schema {schema}; this build understands {SCHEMA}, "
            "so anything newer than that was ignored"
        )
    elif schema is not None and not isinstance(schema, int):
        problems.append(f"the schema is '{schema}', which is not a number")

    scaffold = document.get("scaffold")
    if scaffold is not None and not isinstance(scaffold, Mapping):
        problems.append("'scaffold' is not an object, so it was ignored")
        scaffold = None
    scaffold = scaffold or {}

    settings = Settings(
        workspace_root=_text(scaffold, "workspace_root", current.workspace_root)
        or DEFAULT_WORKSPACE_ROOT,
        bundle_prefix=_text(scaffold, "bundle_prefix", current.bundle_prefix)
        or DEFAULT_BUNDLE_PREFIX,
        scripts_root=_text(scaffold, "scripts_root", current.scripts_root)
        or DEFAULT_SCRIPTS_ROOT,
        templates=_sources(document, "templates", current.templates, problems),
        scripts=_sources(document, "scripts", current.scripts, problems),
        script_checks=_checks(document, current.script_checks, problems),
        updates=_updates(document, current.updates, problems),
    )
    return settings, tuple(problems)


def _text(section: Mapping[str, Any], key: str, fallback: str) -> str:
    value = section.get(key)
    if value is None:
        return fallback
    return str(value).strip()


def _sources(
    document: Mapping[str, Any],
    key: str,
    fallback: Mapping[str, TemplateSource],
    problems: list[str],
) -> dict[str, TemplateSource]:
    section = document.get(key)
    if section is None:
        return dict(fallback)
    if not isinstance(section, Mapping):
        problems.append(f"'{key}' is not an object, so it was ignored")
        return dict(fallback)

    sources: dict[str, TemplateSource] = {}
    for name, entry in section.items():
        if not isinstance(entry, Mapping):
            problems.append(f"{key}.{name} is not an object, so it was ignored")
            continue
        url = str(entry.get("url", "")).strip()
        if not url:
            # A pin with no URL pins nothing; the TOML writer drops these too,
            # so keeping one here would produce a document that does not survive
            # a save.
            continue
        sources[str(name)] = TemplateSource(
            url=url, ref=str(entry.get("ref", "")).strip()
        )
    return sources


def _checks(
    document: Mapping[str, Any],
    fallback: Mapping[str, bool],
    problems: list[str],
) -> dict[str, bool]:
    section = document.get("script_checks")
    if section is None:
        return dict(fallback)
    if not isinstance(section, Mapping):
        problems.append("'script_checks' is not an object, so it was ignored")
        return dict(fallback)
    checks: dict[str, bool] = {}
    for name, value in section.items():
        if not isinstance(value, bool):
            problems.append(f"script_checks.{name} is not true or false, so it was ignored")
            continue
        checks[str(name)] = value
    return checks


def _updates(
    document: Mapping[str, Any],
    fallback: UpdateSource,
    problems: list[str],
) -> UpdateSource:
    section = document.get("updates")
    if section is None:
        return fallback
    if not isinstance(section, Mapping):
        problems.append("'updates' is not an object, so it was ignored")
        return fallback

    prereleases = section.get("include_prereleases", fallback.include_prereleases)
    if not isinstance(prereleases, bool):
        problems.append("updates.include_prereleases is not true or false, so it was ignored")
        prereleases = fallback.include_prereleases

    return UpdateSource(
        repository=_text(section, "repository", fallback.repository),
        api_base=_text(section, "api_base", fallback.api_base) or DEFAULT_API_BASE,
        include_prereleases=prereleases,
        asset_pattern=_text(section, "asset_pattern", fallback.asset_pattern)
        or DEFAULT_ASSET_PATTERN,
    )
