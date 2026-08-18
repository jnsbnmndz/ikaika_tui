"""One walk through the actions a stack's script repository declares.

Two menus are built out of the same store. Components offers what a repository
can add to a project that already exists; Build offers what it can run. The
choosing, the version prompt, the form and the panel are the same either way,
so they live here and the caller says only which half of the catalogue it is
asking about — a stack menu on one side, a filter on the other.

Kept out of both capabilities rather than written twice, because the parts of
this that are easy to get wrong are the parts that are not visible in it: that
the version prompt comes *before* the menu built from the copy in question,
that a fetch with no panel behind it says so through `working`, and that a
problem is carried onto the menu the user lands on instead of written behind
the screen that covers it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from company_tui.domain.capability import CANCELLED
from company_tui.domain.script_config import ScriptAction, ScriptUpdate
from company_tui.domain.template_pack import TemplatePack
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

READING = "Reading the {stack} scripts..."
UPDATING = "Updating the {stack} scripts..."
"""What the app says while the step between two menus is taking a while.

Both go to the network — the first fetches the ref to compare versions against,
the second may throw the store away and clone it again — and neither has a panel
to narrate into, so without this the user is looking at an empty frame."""

Filter = Callable[[Sequence[ScriptAction]], tuple[ScriptAction, ...]]


class Ending(Enum):
    """How a walk stopped, which is not the same question as what it returned."""

    BACK = auto()
    """The user left for the stack menu, or the store could not be read."""

    NOTHING = auto()
    """This stack's store offers nothing of the kind asked for.

    Not a failure and not something to report: a stack whose scripts declare no
    generators has whatever the pack itself can generate, and one that declares
    no workflows has the build it ships with. The caller knows which."""

    DONE = auto()


@dataclass(frozen=True, slots=True)
class Walk:
    ending: Ending
    exit_code: int = 0
    notice: str = ""
    """Why the walk came back, said on the menu the user lands on."""


async def walk(
    console: Ui,
    pack: TemplatePack,
    *,
    wanted: Filter,
    settled: bool = False,
) -> Walk:
    """Offer this stack's actions of one kind, and run whichever is chosen.

    `settled` says the store's version has already been answered for this walk
    through the capability — a "keep" is about the store as it is now, and
    asking again on the way back in would be asking the same question twice.
    """
    action: ScriptAction | None = None
    notice = ""

    while True:
        if action is None:
            catalogue = await console.working(
                READING.format(stack=pack.info.name), pack.script_actions()
            )
            if catalogue.problem:
                return Walk(Ending.BACK, notice=catalogue.problem)

            offered = wanted(catalogue.actions)
            if not offered:
                return Walk(Ending.NOTHING)

            if catalogue.stale and not settled:
                # Asked before the workflows are offered, because what they are
                # is read out of the copy in question — a menu built from the
                # old manifest and then replaced under the user is a menu they
                # chose from and did not get.
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

            action = await console.choose_script_action(offered, notice)
            notice = ""
            if action is None:
                return Walk(Ending.BACK)
            continue

        values = await console.open_run_panel(action.name, pack.script_options(action))
        if values is None:
            action = None
            continue

        result = await console.run_in_panel(pack.run_script(action, values))
        if result is None:
            failure = console.panel_failure()
            if await console.close_run_panel(failure or STOPPED_MESSAGE, ok=False):
                continue
            return Walk(Ending.DONE, exit_code=FAILED if failure else CANCELLED)

        # Generating one file is usually generating several, so the panel offers
        # itself back with the same form still filled in.
        if await console.close_run_panel(result.message, ok=result.exit_code == 0):
            continue
        return Walk(Ending.DONE, exit_code=result.exit_code)


__all__ = ["Ending", "FAILED", "STOPPED_MESSAGE", "Walk", "walk"]
