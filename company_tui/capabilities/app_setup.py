"""Carrying this machine's configuration out as one JSON file, and back in.

Settings live in TOML beside a repository, which is the right place for a file a
team edits together. This is the other need: a new laptop, a rebuilt machine, or
a colleague who should have the same setup - one file, moved, and everything
matches. It reuses the run panel like Settings does, so the same form is on the
left and the same terminal on the right saying exactly which file was touched.


EXPORT WRITES A FILE. IMPORT WRITES YOUR SETTINGS.

Those are not the same risk, so they are not treated the same way. Export names
the file and refuses to overwrite one unless told to. Import shows every value it
read and every problem it found, and writes nothing until the form is submitted
again - because an import is a settings edit that arrives from outside, and the
one thing worse than a typo is a typo somebody else made.


IMPORTING REPORTS WHAT IT IGNORED

`read_document` is deliberately forgiving: an unreadable field keeps the value
already in place rather than failing the whole file. That is only defensible if
the gaps are visible, so every problem it found is printed. "Imported" over a
document half of which was skipped is the outcome this exists to avoid.
"""

import json
from pathlib import Path

from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort, ConfigScope, Settings
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.settings_document import (
    KIND,
    SCHEMA,
    read_document,
    write_document,
)
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

ACTION_KEY = "action"
FILE_KEY = "file"
SCOPE_KEY = "scope"
OVERWRITE_KEY = "overwrite"

EXPORT = "export"
IMPORT = "import"

DEFAULT_NAME = "generic-settings.json"


class AppSetupCapability(Capability):
    def __init__(self, console: Ui, config: ConfigPort) -> None:
        self._console = console
        self._config = config

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="app_setup",
            name="App Setup",
            description="Export or import the whole configuration",
        )

    async def execute(self) -> int:
        while True:
            # Re-read each time round: the previous pass may have imported the
            # settings this form is about to show.
            values = await self._console.open_run_panel(
                "App Setup", self._options(self._config.settings())
            )
            if values is None:
                return CANCELLED

            outcome = await self._console.run_in_panel(self._act(values))
            if outcome is None:
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            message, ok = outcome
            if await self._console.close_run_panel(message, ok=ok):
                continue
            return 0 if ok else FAILED

    def _options(self, settings: Settings) -> tuple[Option, ...]:
        active = self._config.active_location()
        suggested = Path.cwd() / DEFAULT_NAME
        return (
            Option(
                key=ACTION_KEY,
                label="What to do",
                kind=OptionKind.CHOICE,
                choices=(EXPORT, IMPORT),
                default=EXPORT,
                help="export: write this configuration out · import: read one in.",
            ),
            Option(
                key=FILE_KEY,
                label="JSON file",
                kind=OptionKind.FILE,
                default=str(suggested),
                help="Written when exporting, read when importing.",
            ),
            Option(
                key=SCOPE_KEY,
                label="Import into",
                kind=OptionKind.CHOICE,
                choices=tuple(scope.value for scope in ConfigScope),
                default=ConfigScope.PROJECT.value,
                help="Ignored when exporting. project: beside this repository.",
            ),
            Option(
                key=OVERWRITE_KEY,
                label="Overwrite the file",
                kind=OptionKind.BOOLEAN,
                default=False,
                help="Exporting refuses to replace an existing file without this.",
            ),
            Option(
                key="reading_now",
                label="Reading now",
                kind=OptionKind.INFO,
                default=str(active) if active else "the built-in defaults",
            ),
            Option(
                key="current_prefix",
                label="Bundle prefix",
                kind=OptionKind.INFO,
                default=settings.bundle_prefix,
            ),
            Option(
                key="current_updates",
                label="Update source",
                kind=OptionKind.INFO,
                default=settings.updates.repository or "not configured",
            ),
            Option(
                key="schema",
                label="Document schema",
                kind=OptionKind.INFO,
                default=f"{KIND} v{SCHEMA}",
            ),
        )

    async def _act(self, values: OptionValues) -> tuple[str, bool]:
        action = str(values.get(ACTION_KEY, EXPORT)).strip() or EXPORT
        raw = str(values.get(FILE_KEY, "")).strip()
        if not raw:
            return ("No file was given.", False)

        # expanduser, because a form is a place people type ~ and a Path that
        # keeps it makes a directory literally called "~" on the first write.
        path = Path(raw).expanduser()
        if action == IMPORT:
            return await self._import(path, values)
        return self._export(path, values)

    def _export(self, path: Path, values: OptionValues) -> tuple[str, bool]:
        if path.exists() and not values.get(OVERWRITE_KEY):
            return (
                f"{path} already exists - tick 'Overwrite the file' to replace it.",
                False,
            )
        if path.is_dir():
            return (f"{path} is a directory, not a file.", False)

        document = write_document(self._config.settings())
        self._console.write(f"Writing {path}...")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(document, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            return (f"Could not write {path}: {error}", False)

        for line in json.dumps(document, indent=2).splitlines():
            self._console.write(line)
        size = path.stat().st_size
        return (f"Exported the configuration to {path} ({size} bytes)", True)

    async def _import(self, path: Path, values: OptionValues) -> tuple[str, bool]:
        if not path.is_file():
            return (f"There is no file at {path}.", False)

        self._console.write(f"Reading {path}...")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as error:
            return (f"Could not read {path}: {error}", False)
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            return (f"{path} is not valid JSON: {error}", False)

        settings, problems = read_document(document, self._config.settings())

        self._console.write(f"Workspace root: {settings.workspace_root}")
        self._console.write(f"Bundle prefix: {settings.bundle_prefix}")
        self._console.write(f"Scripts root: {settings.scripts_root}")
        self._console.write(
            f"Update source: {settings.updates.repository or 'not configured'}"
        )
        for key in sorted(settings.templates):
            self._console.write(f"{key}: {settings.templates[key].described}")
        for key in sorted(settings.scripts):
            self._console.write(f"{key} scripts: {settings.scripts[key].described}")

        # Printed before the write, so a document that half-applied says so in
        # the same breath as saying it applied.
        for problem in problems:
            self._console.write(f"ignored: {problem}")

        scope = self._scope(values)
        self._console.write(f"Writing {self._config.location(scope)}...")
        written = self._config.save(settings, scope)

        if problems:
            return (
                f"Imported into {written}, but {len(problems)} thing(s) were ignored.",
                False,
            )
        return (f"Imported {path} into {written}", True)

    @staticmethod
    def _scope(values: OptionValues) -> ConfigScope:
        chosen = str(values.get(SCOPE_KEY, "")).strip()
        return next(
            (scope for scope in ConfigScope if scope.value == chosen),
            ConfigScope.PROJECT,
        )
