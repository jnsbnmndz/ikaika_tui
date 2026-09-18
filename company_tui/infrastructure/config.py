"""Settings read from and written to the toolbox's own TOML file."""

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
    CHANNEL_ANY,
    CHANNEL_OFFICIAL,
    CHANNELS,
    DEFAULT_API_BASE,
    DEFAULT_ASSET_PATTERN,
    DEFAULT_REPOSITORY,
    UpdateSource,
)

CONFIG_NAME = naming.CONFIG_NAME
HOME_CONFIG = naming.store_dir() / CONFIG_NAME


def settings_file(directory: Path) -> Path:
    """This directory's settings file, whichever name it already goes by."""
    for name in naming.config_names():
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return directory / CONFIG_NAME

TEMPLATES_SECTION = "templates"
SCRIPTS_SECTION = "scripts"
UPDATES_SECTION = "updates"
EXPERIMENTAL_SECTION = "experimental"

HEADER = f"# {naming.APP_TITLE} settings."


def quote(value: str) -> str:
    """A TOML basic string. Windows paths are full of the one character that."""
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
    updates = settings.updates
    update_lines = []
    repository = updates.repository.strip()
    if not repository:
        update_lines.append('repository = ""')
    elif repository != DEFAULT_REPOSITORY:
        update_lines.append(f"repository = {quote(repository)}")
    if updates.api_base.strip() and updates.api_base.strip() != DEFAULT_API_BASE:
        update_lines.append(f"api_base = {quote(updates.api_base.strip())}")
    if updates.channel != CHANNEL_OFFICIAL:
        update_lines.append(f"channel = {quote(updates.channel)}")
    if updates.asset_pattern.strip() and updates.asset_pattern.strip() != DEFAULT_ASSET_PATTERN:
        update_lines.append(f"asset_pattern = {quote(updates.asset_pattern.strip())}")
    if update_lines:
        lines += ["", f"[{UPDATES_SECTION}]", *update_lines]

    experimental = []
    if settings.interactive_lists:
        experimental.append("interactive_lists = true")
    if settings.timed_prompts:
        experimental.append("timed_prompts = true")
    if settings.browser_view:
        experimental.append("browser_view = true")
    if experimental:
        lines += ["", f"[{EXPERIMENTAL_SECTION}]", *experimental]

    for key in sorted(settings.templates):
        source = settings.templates[key]
        if not source.url:
            continue
        lines += ["", f"[{TEMPLATES_SECTION}.{key}]", f"url = {quote(source.url)}"]
        if source.ref:
            lines.append(f"ref = {quote(source.ref)}")

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
        configured = section.get("repository")
        return UpdateSource(
            repository=(
                DEFAULT_REPOSITORY if configured is None else str(configured).strip()
            ),
            api_base=str(section.get("api_base", "")).strip() or DEFAULT_API_BASE,
            channel=self._channel_of(section),
            asset_pattern=str(section.get("asset_pattern", "")).strip()
            or DEFAULT_ASSET_PATTERN,
            check_on_launch=section.get("check_on_launch", True) is not False,
        )

    @staticmethod
    def _channel_of(section: dict) -> str:
        """The channel, falling back to the boolean this key replaced."""
        named = str(section.get("channel", "")).strip().lower()
        if named in CHANNELS:
            return named
        return CHANNEL_ANY if section.get("include_prereleases") is True else CHANNEL_OFFICIAL

    def interactive_lists(self) -> bool:
        return self._section(EXPERIMENTAL_SECTION).get("interactive_lists") is True

    def timed_prompts(self) -> bool:
        return self._section(EXPERIMENTAL_SECTION).get("timed_prompts") is True

    def browser_view(self) -> bool:
        return self._section(EXPERIMENTAL_SECTION).get("browser_view") is True

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
            interactive_lists=self.interactive_lists(),
            timed_prompts=self.timed_prompts(),
            browser_view=self.browser_view(),
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
