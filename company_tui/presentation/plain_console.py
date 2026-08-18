from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from company_tui.domain.capability import Capability
from company_tui.domain.options import Option, OptionKind, OptionValue
from company_tui.domain.script_config import ScriptAction, ScriptCatalogue, ScriptUpdate
from company_tui.domain.template_pack import ScaffoldTarget, ScaffoldTargetOption, TemplatePack

T = TypeVar("T")


class PlainConsole:
    def __init__(self) -> None:
        # See `close_run_panel`: the run has already been acknowledged once.
        self._result_acknowledged = False
        self._failure = ""

    def write(self, message: str = "") -> None:
        print(message)

    async def start_run(
        self, workflow: Callable[[], Awaitable[None]], label: str
    ) -> None:
        """One at a time, in the order they were asked for.

        There is nowhere for a second run to go here: a script has one stdout
        and one stdin, and two workflows narrating into them at once would be
        two workflows nobody can read or answer.
        """
        await workflow()

    def error(self, message: str) -> None:
        print(f"Error: {message}")

    async def ask(self, prompt: str) -> str:
        return input(f"{prompt}: ").strip()

    async def confirm(self, prompt: str) -> bool:
        return (await self.ask(f"{prompt} [y/N]")).lower() in ("y", "yes")

    async def choose_capability(
        self,
        capabilities: Sequence[Capability],
    ) -> Capability | None:
        self._result_acknowledged = False
        index = await self._select(
            "Company Developer Toolbox",
            [(item.info.name, item.info.description) for item in capabilities],
            zero_label="Exit",
        )
        if index is None:
            return None
        return capabilities[index]

    async def choose_scaffold_target(
        self,
        options: Sequence[ScaffoldTargetOption],
        notice: str = "",
    ) -> ScaffoldTarget | None:
        if notice:
            self.error(notice)
        index = await self._select(
            "What do you want to scaffold?",
            [(option.name, option.description) for option in options],
        )
        if index is None:
            return None
        return options[index].target

    async def choose_template_pack(
        self,
        packs: Sequence[TemplatePack],
        notice: str = "",
    ) -> TemplatePack | None:
        if notice:
            self.error(notice)
        index = await self._select(
            "Choose a stack",
            [(pack.info.name, pack.info.description) for pack in packs],
        )
        if index is None:
            return None
        return packs[index]

    async def choose_script_action(
        self,
        actions: Sequence[ScriptAction],
        notice: str = "",
    ) -> ScriptAction | None:
        if notice:
            self.error(notice)
        index = await self._select(
            "Choose a workflow",
            [(action.name, action.summary) for action in actions],
        )
        if index is None:
            return None
        return actions[index]

    async def choose_script_update(
        self, catalogue: ScriptCatalogue
    ) -> ScriptUpdate | None:
        self.write(
            f"Scripts in {catalogue.location} are {catalogue.installed}; "
            f"{catalogue.available} is published."
        )
        index = await self._select(
            "These scripts are not the published ones",
            [
                ("Re-clone", "Replace the copy in the store"),
                ("Keep this copy", "Carry on with what is installed"),
                ("Stop asking", "Keep it, and never check again"),
            ],
        )
        if index is None:
            return None
        return (ScriptUpdate.RECLONE, ScriptUpdate.KEEP, ScriptUpdate.SILENCE)[index]

    async def _select(
        self,
        title: str,
        entries: Sequence[tuple[str, str]],
        zero_label: str = "Back",
    ) -> int | None:
        self.write()
        self.write(title)
        self.write("=" * len(title))
        for position, (name, description) in enumerate(entries, start=1):
            self.write(f"{position}. {name} — {description}")
        self.write(f"0. {zero_label}")

        choice = await self.ask("Choose an action")
        if choice == "0":
            return None
        if not choice.isdigit():
            self.error("Enter a menu number")
            return await self._select(title, entries, zero_label)

        index = int(choice) - 1
        if index not in range(len(entries)):
            self.error("That option does not exist")
            return await self._select(title, entries, zero_label)
        return index

    async def pause(self) -> None:
        if self._result_acknowledged:
            self._result_acknowledged = False
            return
        input("Press Enter to continue...")

    async def open_run_panel(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
    ) -> dict[str, OptionValue] | None:
        """No two panes here — the same flags, asked one at a time."""
        self.write()
        self.write(" › ".join([*trail, title]) if trail else title)
        values: dict[str, OptionValue] = {}
        for option in options:
            if option.kind is OptionKind.INFO:
                self.write(f"{option.label}: {option.render(values)}")
            elif option.kind is OptionKind.BOOLEAN:
                values[option.key] = await self.confirm(option.label)
            else:
                answer = await self.ask(option.label)
                values[option.key] = answer or str(option.default)
        return values

    async def working(self, label: str, work: Awaitable[T]) -> T:
        """Said once and then waited for: a script's log is the whole record."""
        self.write(label)
        return await work

    async def run_in_panel(self, work: Awaitable[T]) -> T | None:
        """Nothing to stop here: Ctrl+C is already the terminal's own answer.

        An error is still reported rather than raised, so a scripted run ends
        with a message and an exit code instead of a traceback.
        """
        self._failure = ""
        try:
            return await work
        except Exception as error:
            self._failure = f"{type(error).__name__}: {error}"
            self.error(self._failure)
            return None

    def panel_failure(self) -> str:
        return self._failure

    async def close_run_panel(self, message: str = "", ok: bool = True) -> bool:
        """Always done after one run: repeating a step is what a script is for."""
        if message:
            self.write(message)
        await self.pause()
        self._result_acknowledged = True
        return False
