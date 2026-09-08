"""Settings read from and written to the toolbox's own TOML file.

Looked for beside the project first and in the user's home second, so a team can
pin a template for one repository without changing what everyone else gets.

    [scaffold]
    workspace_root = "~/work"
    bundle_prefix  = "com.dti"
    scripts_root   = "~/.dti/scripts"

    [templates.react_native]
    url = "https://github.com/JDM-Github/react_native_structure.git"
    ref = "v1.2.0"

    [scripts.react_native]
    url = "https://github.com/JDM-Github/react_native_scripts.git"
    ref = "v1.0.0"

    [updates]
    repository = "owner/name"

Either filename is read - the one before the rename included - and a file that
already exists keeps its name. Nothing here is required. A malformed or
unreadable file falls back to the
defaults rather than stopping the toolbox: settings that cannot be parsed are a
reason to warn, not a reason to be unable to scaffold anything.

Written by hand rather than with a library, because the shape is four keys and a
table per stack, and `tomllib` only reads.
"""

import tomllib
from pathlib import Path
from typing import Any

from company_tui.domain import naming
from company_tui.domain.config import (
    DEFAULT_BUNDLE_PREFIX,
    DEFAULT_SCRIPTS_ROOT,
    DEFAULT_WORKSPACE_ROOT,
    ConfigPort,
    ConfigScope,
    Settings,
    TemplateSource,
)
from company_tui.domain.updates import (
    DEFAULT_API_BASE,
    DEFAULT_ASSET_PATTERN,
    UpdateSource,
)

CONFIG_NAME = naming.CONFIG_NAME
HOME_CONFIG = naming.store_dir() / CONFIG_NAME


def settings_file(directory: Path) -> Path:
    """This directory's settings file, whichever name it already goes by.

    A file somebody has edited keeps its name: preferring the new one would read
    an empty default over a real configuration and then write the answer
    somewhere the old file is still sitting, saying something else.
    """
    for name in naming.config_names():
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return directory / CONFIG_NAME

TEMPLATES_SECTION = "templates"
SCRIPTS_SECTION = "scripts"
UPDATES_SECTION = "updates"

HEADER = f"# {naming.APP_TITLE} settings."


def quote(value: str) -> str:
    """A TOML basic string. Windows paths are full of the one character that
    would otherwise start an escape, so it is escaped rather than hoped about."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render(settings: Settings) -> str:
    lines = [
        HEADER,
        "",
        "[scaffold]",
        f"workspace_root = {quote(settings.workspace_root)}",
        f"bundle_prefix = {quote(settings.bundle_prefix)}",
        f"scripts_root = {quote(settings.scripts_root)}",
    ]
    # Only when it differs from the defaults. An [updates] table repeating the
    # built-in values in every settings file is noise that reads as configuration,
    # and the next person to change a default would leave every existing file
    # pinned to the old one.
    updates = settings.updates
    update_lines = []
    if updates.repository.strip():
        update_lines.append(f"repository = {quote(updates.repository.strip())}")
    if updates.api_base.strip() and updates.api_base.strip() != DEFAULT_API_BASE:
        update_lines.append(f"api_base = {quote(updates.api_base.strip())}")
    if updates.include_prereleases:
        update_lines.append("include_prereleases = true")
    if updates.asset_pattern.strip() and updates.asset_pattern.strip() != DEFAULT_ASSET_PATTERN:
        update_lines.append(f"asset_pattern = {quote(updates.asset_pattern.strip())}")
    if update_lines:
        lines += ["", f"[{UPDATES_SECTION}]", *update_lines]

    for key in sorted(settings.templates):
        source = settings.templates[key]
        if not source.url:
            continue
        lines += ["", f"[{TEMPLATES_SECTION}.{key}]", f"url = {quote(source.url)}"]
        if source.ref:
            lines.append(f"ref = {quote(source.ref)}")

    # A script table is worth writing for a URL or for a `check = false`, and
    # the second can outlive the first: somebody who stopped being asked about a
    # stack has said something about it even after the URL goes back to default.
    for key in sorted(set(settings.scripts) | set(settings.script_checks)):
        source = settings.scripts.get(key, TemplateSource(url=""))
        checked = settings.script_checks.get(key, True)
        if not source.url and checked:
            continue
        lines += ["", f"[{SCRIPTS_SECTION}.{key}]"]
        if source.url:
            lines.append(f"url = {quote(source.url)}")
            if source.ref:
                lines.append(f"ref = {quote(source.ref)}")
        if not checked:
            lines.append("check = false")
    return "\n".join(lines) + "\n"


class FileConfig(ConfigPort):
    def __init__(self, project: Path | None = None, user: Path | None = None) -> None:
        self._project = project if project is not None else settings_file(Path.cwd())
        self._user = (
            user if user is not None else settings_file(naming.store_dir())
        )
        self._settings: dict[str, Any] | None = None
        self._source: Path | None = None
        self.problem = ""

    @property
    def source(self) -> Path | None:
        self._loaded()
        return self._source

    def template_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        return self._pinned(TEMPLATES_SECTION, pack_key, default)

    def script_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        return self._pinned(SCRIPTS_SECTION, pack_key, default)

    def bundle_prefix(self) -> str:
        prefix = str(self._section("scaffold").get("bundle_prefix", "")).strip()
        return prefix or DEFAULT_BUNDLE_PREFIX

    def workspace_root(self) -> Path:
        root = str(self._section("scaffold").get("workspace_root", "")).strip()
        return Path(root).expanduser() if root else Path(DEFAULT_WORKSPACE_ROOT)

    def scripts_root(self) -> Path:
        root = str(self._section("scaffold").get("scripts_root", "")).strip()
        return Path(root or DEFAULT_SCRIPTS_ROOT).expanduser()

    def script_check(self, pack_key: str) -> bool:
        entry = self._section(SCRIPTS_SECTION).get(pack_key)
        if not isinstance(entry, dict):
            return True
        return entry.get("check", True) is not False

    def update_source(self) -> UpdateSource:
        section = self._section(UPDATES_SECTION)
        return UpdateSource(
            repository=str(section.get("repository", "")).strip(),
            api_base=str(section.get("api_base", "")).strip() or DEFAULT_API_BASE,
            include_prereleases=section.get("include_prereleases", False) is True,
            asset_pattern=str(section.get("asset_pattern", "")).strip()
            or DEFAULT_ASSET_PATTERN,
            # `is not False`, so a missing key and a malformed one both leave the
            # check on. The same reading as `script_check` above: a setting nobody
            # wrote is not a setting saying no.
            check_on_launch=section.get("check_on_launch", True) is not False,
        )

    def settings(self) -> Settings:
        scaffold = self._section("scaffold")
        return Settings(
            workspace_root=str(scaffold.get("workspace_root", "")).strip()
            or DEFAULT_WORKSPACE_ROOT,
            bundle_prefix=str(scaffold.get("bundle_prefix", "")).strip()
            or DEFAULT_BUNDLE_PREFIX,
            templates=self._pinned_sources(TEMPLATES_SECTION),
            scripts_root=str(scaffold.get("scripts_root", "")).strip()
            or DEFAULT_SCRIPTS_ROOT,
            scripts=self._pinned_sources(SCRIPTS_SECTION),
            updates=self.update_source(),
            script_checks={
                key: entry.get("check", True) is not False
                for key, entry in self._section(SCRIPTS_SECTION).items()
                if isinstance(entry, dict)
            },
        )

    def _pinned(
        self, section: str, pack_key: str, default: TemplateSource
    ) -> TemplateSource:
        entry = self._section(section).get(pack_key)
        if not isinstance(entry, dict):
            return default
        return TemplateSource(
            url=str(entry.get("url", default.url)) or default.url,
            ref=str(entry.get("ref", default.ref)),
        )

    def _pinned_sources(self, section: str) -> dict[str, TemplateSource]:
        return {
            key: TemplateSource(
                url=str(entry.get("url", "")), ref=str(entry.get("ref", ""))
            )
            for key, entry in self._section(section).items()
            if isinstance(entry, dict)
        }

    def location(self, scope: ConfigScope) -> Path:
        return self._user if scope is ConfigScope.USER else self._project

    def active_location(self) -> Path | None:
        return self.source

    def save(self, settings: Settings, scope: ConfigScope) -> Path:
        path = self.location(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(settings), encoding="utf-8")
        # Everything holds one instance of this, so forgetting what was read is
        # what makes the change take effect without restarting the toolbox.
        self._settings = None
        self._source = None
        self.problem = ""
        return path

    def _section(self, name: str) -> dict[str, Any]:
        section = self._loaded().get(name)
        return section if isinstance(section, dict) else {}

    def _loaded(self) -> dict[str, Any]:
        if self._settings is None:
            self._settings = self._read()
        return self._settings

    def _read(self) -> dict[str, Any]:
        for path in (self._project, self._user):
            try:
                if not path.is_file():
                    continue
                with path.open("rb") as handle:
                    settings = tomllib.load(handle)
            except (OSError, tomllib.TOMLDecodeError) as error:
                self.problem = f"{path}: {error}"
                continue
            self._source = path
            return settings
        return {}
