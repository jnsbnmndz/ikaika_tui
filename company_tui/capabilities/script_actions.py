"""One walk through the actions a stack's script repository declares."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from company_tui.domain.capability import CANCELLED
from company_tui.domain.config import ConfigPort
from company_tui.domain.options import Option, OptionValues
from company_tui.domain.script_config import ScriptAction, ScriptUpdate
from company_tui.domain.template_pack import TemplatePack
from company_tui.presentation.ui import Ui
from company_tui.templates.scripts import browses

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

READING = "Reading the {stack} scripts..."
UPDATING = "Updating the {stack} scripts..."
"""What the app says while the step between two menus is taking a while."""

Filter = Callable[[Sequence[ScriptAction]], tuple[ScriptAction, ...]]


class Ending(Enum):
    """How a walk stopped, which is not the same question as what it returned."""

    BACK = auto()
    """The user left for the stack menu, or the store could not be read."""

    NOTHING = auto()
    """This stack's store offers nothing of the kind asked for."""

    DONE = auto()


@dataclass(frozen=True, slots=True)
class Walk:
    ending: Ending
    exit_code: int = 0
    notice: str = ""
    """Why the walk came back, said on the menu the user lands on."""

def answers(options: Sequence[Option]) -> OptionValues:
    """A form's answers without a form, which is what a browser action is launched on.

    A form is for a run you configure, and a place you move around in is not one, so
    what the manifest already says is the whole of what it is given.
    """
    return {option.key: option.default for option in options}


async def walk(
    console: Ui,
    pack: TemplatePack,
    *,
    wanted: Filter,
    config: ConfigPort | None = None,
    settled: bool = False,
) -> Walk:
    """Offer this stack's actions of one kind, and run whichever is chosen."""
    action: ScriptAction | None = None
    notice = ""

    while True:
        if action is None:
            catalogue = await console.working(
                READING.format(stack=pack.info.name), pack.script_actions()
            )
            if catalogue.problem:
                return Walk(Ending.BACK, notice=catalogue.problem)

            if catalogue.stale and not settled:
                choice = await console.choose_script_update(catalogue)
                if choice is None:
                    return Walk(Ending.BACK)
                outcome = await console.working(
                    UPDATING.format(stack=pack.info.name),
                    pack.apply_script_update(choice),
                )
                notice = outcome.message
                settled = choice is not ScriptUpdate.RECLONE
                continue

            offered = wanted(catalogue.actions)
            if not offered:
                return Walk(Ending.NOTHING, notice=notice)

            action = await console.choose_script_action(offered, notice)
            notice = ""
            if action is None:
                return Walk(Ending.BACK)
            continue

        options = pack.script_options(action)
        if config is not None and browses(action, config):
            outcome = await console.browse(
                action.name, pack.run_script(action, answers(options)),
                subtitle=action.summary,
            )
            notice = "" if outcome is None else outcome.message
            action = None
            continue

        values = await console.open_run_panel(action.name, options)
        if values is None:
            action = None
            continue

        result = await console.run_in_panel(pack.run_script(action, values))
        if result is None:
            failure = console.panel_failure()
            if await console.close_run_panel(failure or STOPPED_MESSAGE, ok=False):
                continue
            return Walk(Ending.DONE, exit_code=FAILED if failure else CANCELLED)

        if await console.close_run_panel(result.message, ok=result.exit_code == 0):
            continue
        return Walk(Ending.DONE, exit_code=result.exit_code)


__all__ = ["FAILED", "STOPPED_MESSAGE", "Ending", "Walk", "walk"]
