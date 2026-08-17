"""Settings read from and written to `ikaika.toml`.

Looked for beside the project first and in the user's home second, so a team can
pin a template for one repository without changing what everyone else gets.

    [scaffold]
    workspace_root = "~/work"
    bundle_prefix  = "com.ikaika"

    [templates.react_native]
    url = "https://github.com/JDM-Github/react_native_structure.git"
    ref = "v1.2.0"

Nothing here is required. A malformed or unreadable file falls back to the
defaults rather than stopping the toolbox: settings that cannot be parsed are a
reason to warn, not a reason to be unable to scaffold anything.

Written by hand rather than with a library, because the shape is four keys and a
table per stack, and `tomllib` only reads.
"""

import tomllib
from pathlib import Path
from typing import Any

from company_tui.domain.config import (
    DEFAULT_BUNDLE_PREFIX,
    DEFAULT_WORKSPACE_ROOT,
    ConfigPort,
    ConfigScope,
    Settings,
    TemplateSource,
)

CONFIG_NAME = "ikaika.toml"
HOME_CONFIG = Path.home() / ".ikaika" / CONFIG_NAME

HEADER = "# IKAIKA developer toolbox settings."


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
    ]
    for key in sorted(settings.templates):
        source = settings.templates[key]
        if not source.url:
            continue
        lines += ["", f"[templates.{key}]", f"url = {quote(source.url)}"]
        if source.ref:
            lines.append(f"ref = {quote(source.ref)}")
    return "\n".join(lines) + "\n"


class FileConfig(ConfigPort):
    def __init__(self, project: Path | None = None, user: Path | None = None) -> None:
        self._project = project if project is not None else Path.cwd() / CONFIG_NAME
        self._user = user if user is not None else HOME_CONFIG
        self._settings: dict[str, Any] | None = None
        self._source: Path | None = None
        self.problem = ""

    @property
    def source(self) -> Path | None:
        self._loaded()
        return self._source

    def template_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        entry = self._section("templates").get(pack_key)
        if not isinstance(entry, dict):
            return default
        return TemplateSource(
            url=str(entry.get("url", default.url)) or default.url,
            ref=str(entry.get("ref", default.ref)),
        )

    def bundle_prefix(self) -> str:
        prefix = str(self._section("scaffold").get("bundle_prefix", "")).strip()
        return prefix or DEFAULT_BUNDLE_PREFIX

    def workspace_root(self) -> Path:
        root = str(self._section("scaffold").get("workspace_root", "")).strip()
        return Path(root).expanduser() if root else Path(DEFAULT_WORKSPACE_ROOT)

    def settings(self) -> Settings:
        templates = {
            key: TemplateSource(
                url=str(entry.get("url", "")), ref=str(entry.get("ref", ""))
            )
            for key, entry in self._section("templates").items()
            if isinstance(entry, dict)
        }
        scaffold = self._section("scaffold")
        return Settings(
            workspace_root=str(scaffold.get("workspace_root", "")).strip()
            or DEFAULT_WORKSPACE_ROOT,
            bundle_prefix=str(scaffold.get("bundle_prefix", "")).strip()
            or DEFAULT_BUNDLE_PREFIX,
            templates=templates,
        )

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
