"""Settings that belong to the company rather than to the code.

Which repository a stack is cloned from, which ref of it is current, what prefix
the organisation's bundle identifiers start with and where projects are kept are
all answers that change without any of this code changing. They are read — and
written — through a port, so pinning a template is an edit to a settings file
rather than a release of the toolbox.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.updates import UpdateSource

DEFAULT_BUNDLE_PREFIX = naming.BUNDLE_PREFIX
DEFAULT_WORKSPACE_ROOT = "."
DEFAULT_SCRIPTS_ROOT = f"~/{naming.STORE_DIR_NAME}/scripts"
"""Where cloned script repositories are kept, for every project on this machine.

One copy per repository rather than one per project: a script repository is the
toolbox's own working material, not a project's, and a dozen projects on one
stack cloning the same dozen templates a dozen times is a dozen copies to keep
in step. Beside the user's `ikaika.toml` for the same reason that lives there —
it belongs to the machine, and nothing in it should arrive in a checkout.
"""


class ConfigScope(Enum):
    """Which of the two settings files an edit belongs in."""

    PROJECT = "project"
    """Beside the repository: what this project's team agreed on."""

    USER = "user"
    """In the user's home: what this machine does by default."""


@dataclass(frozen=True, slots=True)
class TemplateSource:
    url: str
    ref: str = ""
    """Branch or tag to clone; empty means whatever the repository defaults to."""

    @property
    def described(self) -> str:
        return f"{self.url} @ {self.ref}" if self.ref else self.url


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the settings file holds, as one editable value."""

    workspace_root: str = DEFAULT_WORKSPACE_ROOT
    bundle_prefix: str = DEFAULT_BUNDLE_PREFIX
    templates: Mapping[str, TemplateSource] = field(default_factory=dict)
    scripts_root: str = DEFAULT_SCRIPTS_ROOT
    scripts: Mapping[str, TemplateSource] = field(default_factory=dict)
    """Where each stack's script repository is cloned from. Separate from
    `templates` because they answer different questions: a template is what a
    new project is made of, and a script repository is what the toolbox runs
    against a project that already exists. Pinning one is not pinning the
    other."""

    updates: UpdateSource = field(default_factory=UpdateSource)
    """Where the toolbox looks for a newer build of itself.

    Part of the settings rather than a constant, because the answer is a
    property of the deployment and not of the code: a fork, an internal mirror,
    or a GitHub Enterprise host are all the same program pointed somewhere else.
    Edited in Advanced; empty by default, since this has no business guessing
    which repository somebody is running a build of."""

    script_checks: Mapping[str, bool] = field(default_factory=dict)
    """Whether each stack's installed scripts are compared against the remote.

    Only ever written when the answer is no: a stack nobody has said anything
    about is checked, and what puts an entry here is somebody choosing to stop
    being asked. Kept out of `TemplateSource` because it is not a property of
    the repository — the same URL is worth watching in one checkout and not in
    another."""


class ConfigPort(ABC):
    @abstractmethod
    def template_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        """Where `pack_key` clones from, falling back to what the pack ships with."""
        raise NotImplementedError

    @abstractmethod
    def script_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        """Where `pack_key`'s build scripts come from, and which ref of them.

        A separate answer from `template_source`: the two repositories move at
        their own speeds, and pinning the structure a project is cloned from
        should not pin the scripts that maintain it afterwards.
        """
        raise NotImplementedError

    @abstractmethod
    def bundle_prefix(self) -> str:
        """The reverse-DNS prefix new iOS and Android identifiers are built on."""
        raise NotImplementedError

    @abstractmethod
    def workspace_root(self) -> Path:
        """Where new projects are created unless the user says otherwise."""
        raise NotImplementedError

    @abstractmethod
    def scripts_root(self) -> Path:
        """Where cloned script repositories are kept, shared by every project."""
        raise NotImplementedError

    @abstractmethod
    def script_check(self, pack_key: str) -> bool:
        """Whether to compare this stack's installed scripts against the remote.

        True until somebody says otherwise, because a store nobody looks at goes
        stale silently. The one who says otherwise is the person the question was
        put to, and the answer is a settings edit like every other.
        """
        raise NotImplementedError

    @abstractmethod
    def update_source(self) -> UpdateSource:
        """Where to look for a newer build of the toolbox itself."""
        raise NotImplementedError

    @abstractmethod
    def settings(self) -> Settings:
        """Everything at once, for a form to show and hand back edited."""
        raise NotImplementedError

    @abstractmethod
    def location(self, scope: ConfigScope) -> Path:
        """The file `scope` is read from and written to, whether or not it exists."""
        raise NotImplementedError

    @abstractmethod
    def active_location(self) -> Path | None:
        """The file the current answers came from, or `None` if they are defaults."""
        raise NotImplementedError

    @abstractmethod
    def save(self, settings: Settings, scope: ConfigScope) -> Path:
        """Write `settings` and forget what was read before, returning the file."""
        raise NotImplementedError
