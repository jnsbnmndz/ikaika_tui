"""The walk through a project's own commands, and what it says when there are none.

No disk and no subprocess: the filesystem and the process runner are ports, so a
fake for each is enough to drive the whole capability. What is checked is the
part that is easy to get wrong and impossible to see - which menu the user lands
on after backing out of another, and whether a missing manifest is told apart
from one that simply declares nothing.

The run itself goes through `templates/scripts.py: run_action`, the same function
Build uses, so the assertion worth making here is that the declared command line
reaches the runner filled in - not that a subprocess happened.
"""

import asyncio
import os
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from company_tui.capabilities.scripts import PROJECT_ROOT, ScriptsCapability
from company_tui.domain.capability import CANCELLED
from company_tui.domain.identity import SCRIPT_MANIFEST
from company_tui.domain.options import defaults_for
from company_tui.domain.script_config import action_options
from company_tui.domain.ports import ProcessResult
from company_tui.templates.services import PackServices

ROOT = Path("/proj").resolve()

MANIFEST = """
{
  "version": "1.0.0+1",
  "name": "demo",
  "title": "Demo",
  "description": "A demo",
  "rules": {"global": ["flag", "type", "required", "description", "default"],
            "string": ["allowed_values"], "boolean": []},
  "config": {
    "git": {
      "pull-updates": {
        "description": "Pulls updates from another branch.",
        "args": [{"flag": "Branch", "type": "string", "default": "development"},
                 {"flag": "Prune", "type": "boolean", "default": "false"}],
        "command-after-success": [
          "pwsh -File ${root}/script.ps1 git/pull-updates -Branch ${pull-updates.args.Branch} -Prune ${pull-updates.args.Prune}"
        ]
      }
    },
    "windows": {
      "setup-signing": {"description": "Signing certificates.", "args": [],
                        "command-after-success": ["pwsh -File ${root}/script.ps1 windows/setup-signing"]}
    }
  }
}
"""


@dataclass
class FakeIdentity:
    title: str = "Demo"


class FakeFileSystem:
    def __init__(self, files):
        self.files = files

    def exists(self, path):
        return str(path) in self.files

    def read_text(self, path):
        return self.files[str(path)]


class FakeProcessRunner:
    def __init__(self):
        self.commands = []

    def locate(self, executable):
        return "/usr/bin/" + executable

    async def stream(self, command, on_output, cwd=None):
        self.commands.append((tuple(command), cwd))
        on_output("done")
        return ProcessResult(exit_code=0, stdout="", stderr="")


class FakeFinalizer:
    def require_project(self, root):
        return FakeIdentity()


class StubUi:
    """Answers each menu from a script of choices, then reports what it was asked."""

    def __init__(self, sections=(), actions=(), answers=None, again=False):
        self._sections = list(sections)
        self._actions = list(actions)
        self._answers = answers or {}
        self._again = again
        self.offered_sections = []
        self.offered_actions = []
        self.errors = []
        self.closed = []
        self.lines = []
        self.refresh_runner = None
        self.preview_runner = None
        self.waited_for = []
        self.subtitle = None

    def write(self, message=""):
        if message:
            self.lines.append(str(message))

    def error(self, message):
        self.errors.append(message)

    async def choose_script_section(self, sections, notice=""):
        self.offered_sections.append([s.key for s in sections])
        if not self._sections:
            return None
        wanted = self._sections.pop(0)
        return next((s for s in sections if s.key == wanted), None)

    async def choose_script_action(self, actions, notice=""):
        self.offered_actions.append([a.key for a in actions])
        if not self._actions:
            return None
        wanted = self._actions.pop(0)
        return next((a for a in actions if a.key == wanted), None)

    async def open_run_panel(
        self, title, options, trail=(), refresh=None, preview=None, subtitle=""
    ):
        self.refresh_runner = refresh
        self.preview_runner = preview
        self.subtitle = subtitle
        if self._answers is None:
            return None
        values = dict(defaults_for(tuple(options)))
        values.update(self._answers)
        return values

    async def working(self, label, work):
        self.waited_for.append(label)
        return await work

    async def run_in_panel(self, work):
        return await work

    def panel_failure(self):
        return ""

    async def close_run_panel(self, message="", ok=True):
        self.closed.append((ok, message))
        again, self._again = self._again, False
        return again


def build(console, files):
    runner = FakeProcessRunner()
    services = PackServices(
        console=console,
        file_system=FakeFileSystem(files),
        process_runner=runner,
        config=None,
        finalizer=FakeFinalizer(),
    )
    return ScriptsCapability(console=console, services=services), runner


def run(capability):
    return asyncio.run(capability.execute())


class NothingToRunTest(unittest.TestCase):
    def setUp(self):
        os.environ[PROJECT_ROOT] = str(ROOT)
        self.addCleanup(os.environ.pop, PROJECT_ROOT, None)

    def test_a_project_with_no_manifest_says_so_and_fails(self):
        console = StubUi()
        capability, _ = build(console, {})
        self.assertEqual(1, run(capability))
        self.assertIn(SCRIPT_MANIFEST, console.errors[0])

    def test_a_manifest_declaring_no_commands_is_told_apart_from_a_missing_one(self):
        # Both are "nothing to run", and reporting the second as unreadable would
        # send somebody looking for a syntax error that is not there.
        console = StubUi()
        capability, _ = build(
            console, {str(ROOT / SCRIPT_MANIFEST): '{"name": "demo"}'}
        )
        self.assertEqual(1, run(capability))
        self.assertIn("declares no commands", console.errors[0])

    def test_a_manifest_that_will_not_parse_is_reported_rather_than_raised(self):
        console = StubUi()
        capability, _ = build(console, {str(ROOT / SCRIPT_MANIFEST): "{not json"})
        self.assertEqual(1, run(capability))
        self.assertIn("could not be read", console.errors[0])


class WalkTest(unittest.TestCase):
    def setUp(self):
        os.environ[PROJECT_ROOT] = str(ROOT)
        self.addCleanup(os.environ.pop, PROJECT_ROOT, None)
        self.files = {str(ROOT / SCRIPT_MANIFEST): MANIFEST}

    def test_backing_out_of_the_first_menu_leaves_without_running_anything(self):
        console = StubUi()
        capability, runner = build(console, self.files)
        self.assertEqual(CANCELLED, run(capability))
        self.assertEqual([["git", "windows"]], console.offered_sections)
        self.assertEqual([], runner.commands)

    def test_backing_out_of_the_workflow_menu_returns_to_the_sections(self):
        # One step back rather than out to the front. Getting this wrong is invisible
        # in code and immediately obvious to anyone using it.
        console = StubUi(sections=["git"])
        capability, _ = build(console, self.files)
        self.assertEqual(CANCELLED, run(capability))
        self.assertEqual([["pull-updates"]], console.offered_actions)
        self.assertEqual(2, len(console.offered_sections))

    def test_only_the_chosen_section_s_actions_are_offered(self):
        console = StubUi(sections=["windows"])
        capability, _ = build(console, self.files)
        run(capability)
        self.assertEqual([["setup-signing"]], console.offered_actions)

    def test_running_one_fills_in_the_command_the_document_declared(self):
        console = StubUi(
            sections=["git"], actions=["pull-updates"], answers={"Prune": True}
        )
        capability, runner = build(console, self.files)
        self.assertEqual(0, run(capability))

        self.assertEqual(1, len(runner.commands))
        command, cwd = runner.commands[0]
        self.assertEqual(ROOT, cwd)
        self.assertIn("git/pull-updates", command)
        # The reference is replaced, not left standing, and a boolean arrives as a
        # word rather than as an empty token.
        self.assertEqual("development", command[command.index("-Branch") + 1])
        self.assertEqual("true", command[command.index("-Prune") + 1])

    def test_the_panel_offers_itself_back_rather_than_making_the_user_walk_again(self):
        console = StubUi(
            sections=["git"], actions=["pull-updates"], answers={}, again=True
        )
        capability, runner = build(console, self.files)
        run(capability)
        self.assertEqual(2, len(runner.commands))
        # And it did not walk back through either menu to do it.
        self.assertEqual(1, len(console.offered_actions))

    def test_a_finished_run_reports_success(self):
        console = StubUi(sections=["git"], actions=["pull-updates"], answers={})
        capability, _ = build(console, self.files)
        run(capability)
        self.assertTrue(console.closed[0][0])

REFRESHABLE = """
{
  "version": "1.0.0+1", "name": "demo", "title": "Demo", "description": "A demo",
  "rules": {"global": ["flag", "type", "required", "description", "default", "refresh"],
            "string": ["allowed_values"]},
  "config": {"git": {"pull-updates": {
    "description": "Pulls updates.",
    "args": [{"flag": "Branch", "type": "string", "default": "main",
              "allowed_values": ["main"],
              "refresh": {"label": "Update",
                          "command": "pwsh -File ${root}/script.ps1 refresh git/pull-updates Branch",
                          "preview": "pwsh -File ${root}/script.ps1 refresh git/pull-updates Branch -Preview"}}],
    "command-after-success": ["pwsh -File ${root}/script.ps1 git/pull-updates"]
  }}}
}
"""

AFTER_REFRESH = REFRESHABLE.replace(
    '"allowed_values": ["main"]', '"allowed_values": ["main", "development"]'
)


class CapturingRunner(FakeProcessRunner):
    """Answers `capture`, and remembers what it was asked to run."""

    def __init__(self, exit_code=0, stdout="", stderr="", on_capture=None):
        super().__init__()
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.captured = []
        self._on_capture = on_capture

    async def capture(self, command, cwd=None):
        self.captured.append((tuple(command), cwd))
        if self._on_capture is not None:
            self._on_capture()
        return ProcessResult(
            exit_code=self.exit_code, stdout=self.stdout, stderr=self.stderr
        )


class RefreshTest(unittest.TestCase):
    """The Update button beside a fetched choice."""

    def setUp(self):
        os.environ[PROJECT_ROOT] = str(ROOT)
        self.addCleanup(os.environ.pop, PROJECT_ROOT, None)

    def build(self, runner, manifest=REFRESHABLE):
        console = StubUi()
        files = {str(ROOT / SCRIPT_MANIFEST): manifest}
        file_system = FakeFileSystem(files)
        services = PackServices(
            console=console,
            file_system=file_system,
            process_runner=runner,
            config=None,
            finalizer=FakeFinalizer(),
        )
        capability = ScriptsCapability(console=console, services=services)
        sections, problem = capability._read(ROOT)
        self.assertEqual("", problem)
        option = next(
            o
            for o in action_options(sections[0].actions[0], str(ROOT))
            if o.key == "Branch"
        )
        return capability, option, files

    def refresh(self, capability, option, preview):
        return asyncio.run(capability._refresh(ROOT, option, preview))

    def test_the_option_carries_both_commands(self):
        _, option, _ = self.build(CapturingRunner())
        self.assertIsNotNone(option.refresh)
        self.assertTrue(option.refresh.is_usable)
        self.assertEqual("Update", option.refresh.label)

    def test_a_preview_runs_the_preview_command_and_reports_what_it_said(self):
        runner = CapturingRunner(stdout="Delete 2 local branches?")
        capability, option, _ = self.build(runner)
        outcome = self.refresh(capability, option, True)
        self.assertEqual("Delete 2 local branches?", outcome.message)
        self.assertIn("-Preview", runner.captured[0][0])

    def test_a_preview_offers_no_choices_because_it_changed_nothing(self):
        # The panel must not repaint the field off the back of a dry run.
        runner = CapturingRunner(stdout="Delete 2 local branches?")
        capability, option, _ = self.build(runner)
        self.assertEqual((), self.refresh(capability, option, True).choices)

    def test_the_root_reference_is_filled_in(self):
        runner = CapturingRunner()
        capability, option, _ = self.build(runner)
        self.refresh(capability, option, True)
        command = runner.captured[0][0]
        self.assertFalse(
            any("${root}" in token for token in command), command
        )
        self.assertTrue(any(str(ROOT) in token for token in command), command)
        self.assertEqual(ROOT, runner.captured[0][1])

    def test_acting_re_reads_the_document_for_the_new_values(self):
        # The refresh is what makes the fetched list current, so the values have
        # to come back from the document rather than from what was on screen.
        files = {}

        def rewrite():
            files[str(ROOT / SCRIPT_MANIFEST)] = AFTER_REFRESH

        runner = CapturingRunner(stdout="removed 1", on_capture=rewrite)
        capability, option, live = self.build(runner)
        files = live
        outcome = self.refresh(capability, option, False)
        self.assertEqual(("main", "development"), outcome.choices)
        self.assertEqual("removed 1", outcome.message)
        self.assertTrue(outcome.ok)

    def test_exit_two_is_a_button_with_nothing_behind_it_not_a_failure(self):
        # The dispatcher answers 2 when the command declares no refresh for this
        # parameter. Every fetched choice gets a button, so this is ordinary.
        capability, option, _ = self.build(CapturingRunner(exit_code=2))
        self.assertTrue(self.refresh(capability, option, True).ok)

    def test_a_failing_refresh_is_reported_and_offers_nothing(self):
        runner = CapturingRunner(exit_code=1, stderr="no network")
        capability, option, _ = self.build(runner)
        outcome = self.refresh(capability, option, False)
        self.assertFalse(outcome.ok)
        self.assertIn("no network", outcome.message)
        self.assertEqual((), outcome.choices)

    def test_an_option_with_no_refresh_declines(self):
        capability, option, _ = self.build(CapturingRunner())
        bare = replace(option, refresh=None)
        self.assertFalse(self.refresh(capability, bare, True).ok)

if __name__ == "__main__":
    unittest.main()
