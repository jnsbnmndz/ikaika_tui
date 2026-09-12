"""Python projects, written file by file — the reference for that half of the contract.

React Native shows what a pack that clones looks like. This one shows the other
shape: the pack produces the whole tree itself, including the
`ikaika.script.json` that makes it an IKAIKA project, and then hands it to the
same finalizer so that everything after "the files exist" happens once, in one
place, identically for every stack.
"""

import sys
from collections.abc import Mapping

from company_tui.domain.identity import SCRIPT_MANIFEST, ProjectIdentity, new_manifest
from company_tui.domain.project_name import ProjectName
from company_tui.domain.scaffolding import display_path
from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
)
from company_tui.templates.services import (
    PACKAGE_TOKEN,
    PackServices,
    Renderer,
    clear_destination,
    preview_files,
    run_generator,
)

STACK_NAME = "Python"
PACK_KEY = "python"

REQUIRED_TOOLS: tuple[ToolRequirement, ...] = ()

_PYPROJECT = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "__SLUG__"
version = "__VERSION__"
description = "__DESCRIPTION__"
readme = "README.md"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
__SLUG__ = "__SNAKE__.__main__:main"

[tool.setuptools.packages.find]
include = ["__SNAKE__*"]
"""

_INIT = '''"""__DESCRIPTION__"""

__version__ = "__VERSION__"
'''

_MAIN = '''import os


def main() -> int:
    print(f"__TITLE__ starting in {os.environ.get('ENVIRONMENT', 'development')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_README = """# __TITLE__

__DESCRIPTION__

```sh
python -m __SNAKE__
python -m unittest discover
```
"""

_ENVIRONMENT_EXAMPLE = """ENVIRONMENT=development
"""

_GITIGNORE = """__pycache__/
*.py[cod]
.venv/
build/
dist/
*.egg-info/
.env
"""

_SMOKE_TEST = '''import unittest

from __SNAKE__.__main__ import main


class MainTest(unittest.TestCase):
    def test_it_runs(self) -> None:
        self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
'''


def _project_files(identity: ProjectIdentity) -> dict[str, str]:
    name = identity.name
    package = name.snake

    def fill(template: str) -> str:
        for token, value in (
            ("__SLUG__", name.slug),
            ("__SNAKE__", package),
            ("__TITLE__", identity.title),
            ("__DESCRIPTION__", identity.description),
            ("__VERSION__", identity.version),
        ):
            template = template.replace(token, value)
        return template

    return {
        # The CONSTANT, not the string. This was the old filename written
        # verbatim, so the reference pack scaffolded every new project with a
        # manifest named after the product's previous name - readable, because
        # the resolvers accept it, and wrong, because it is what gets written.
        SCRIPT_MANIFEST: new_manifest(identity),
        "pyproject.toml": fill(_PYPROJECT),
        "README.md": fill(_README),
        ".env.example": _ENVIRONMENT_EXAMPLE,
        ".gitignore": _GITIGNORE,
        f"{package}/__init__.py": fill(_INIT),
        f"{package}/__main__.py": fill(_MAIN),
        "tests/__init__.py": "",
        "tests/test_smoke.py": fill(_SMOKE_TEST),
    }


async def scaffold_new_project(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    root = context.destination
    services.console.write("Checking destination...")
    if not await clear_destination(root, services):
        return PackActionResult(
            available=True, message="Cancelled — nothing was changed.", exit_code=1
        )

    files = _project_files(context.identity)
    preview_files(root, files, services)
    if not await services.console.confirm(
        f"Create {STACK_NAME} project '{context.identity.title}'?"
    ):
        return PackActionResult(
            available=True, message="Cancelled — nothing was changed.", exit_code=1
        )

    services.file_system.write_project(root, files)
    report = await services.finalizer.finalize(root, context.identity)
    return PackActionResult(
        available=True,
        message=(
            f"Created {STACK_NAME} project '{context.identity.title}' "
            f"at {display_path(root)}/ — "
            f"{report.repository}."
        ),
    )


async def scaffold_controller(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    return await run_generator(context, services, GENERATORS, RENDERERS, STACK_NAME)


async def build(services: PackServices) -> PackActionResult:
    result = await services.process_runner.capture((sys.executable, "--version"))
    output = result.stdout or result.stderr
    return PackActionResult(
        available=True,
        message=f"Build runner is ready with {output}.",
        exit_code=result.exit_code,
    )


MODULE = "module"
TEST = "test"

GENERATORS = (
    Generator(
        key=MODULE,
        name="Module",
        description="a module with a dataclass and its test",
        folder=PACKAGE_TOKEN,
    ),
    Generator(
        key=TEST,
        name="Test",
        description="a unittest case on its own",
        folder="tests",
    ),
)

_MODULE_FILE = '''"""__TITLE__."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class __PASCAL__:
    name: str

    def describe(self) -> str:
        return f"__TITLE__: {self.name}"
'''

_TEST_FILE = '''import unittest


class __PASCAL__Test(unittest.TestCase):
    def test_it_is_written(self) -> None:
        self.fail("Write the first __SNAKE__ expectation.")


if __name__ == "__main__":
    unittest.main()
'''


def _fill(template: str, name: ProjectName) -> str:
    for token, value in (
        ("__PASCAL__", name.pascal),
        ("__SNAKE__", name.snake),
        ("__TITLE__", name.title),
    ):
        template = template.replace(token, value)
    return template


def _module(name: ProjectName) -> Mapping[str, str]:
    return {f"{name.snake}.py": _fill(_MODULE_FILE, name)}


def _test(name: ProjectName) -> Mapping[str, str]:
    return {f"test_{name.snake}.py": _fill(_TEST_FILE, name)}


RENDERERS: Mapping[str, Renderer] = {MODULE: _module, TEST: _test}
