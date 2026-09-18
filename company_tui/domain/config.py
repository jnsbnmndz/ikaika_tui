"""Settings that belong to the company rather than to the code."""

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
"""Where cloned script repositories are kept, for every project on this machine."""

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
    """Where each stack's script repository is cloned from. Separate from."""

    updates: UpdateSource = field(default_factory=UpdateSource)
    """Where the toolbox looks for a newer build of itself."""

    script_checks: Mapping[str, bool] = field(default_factory=dict)
    """Whether each stack's installed scripts are compared against the remote."""

    interactive_lists: bool = False
    """Whether a command may hand the toolbox rows to render. Off, and experimental."""

    timed_prompts: bool = False
    """Whether a listing may count down to its own answer. Off, and experimental."""

    browser_view: bool = False
    """Whether an action may open the browser instead of a form. Off, and experimental."""

class ConfigPort(ABC):
    @abstractmethod
    def template_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        """Where `pack_key` clones from, falling back to what the pack ships with."""
        raise NotImplementedError

    @abstractmethod
    def script_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        """Where `pack_key`'s build scripts come from, and which ref of them."""
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
        """Whether to compare this stack's installed scripts against the remote."""
        raise NotImplementedError

    def interactive_lists(self) -> bool:
        """Whether a command may render rows. Half the gate; the other half is the
        command's own declaration, so this alone changes nothing.

        Concrete, and false. An experiment that is off unless something says
        otherwise cannot be turned on by a port that forgot to answer, and an
        implementation written before it existed keeps working unchanged.
        """
        return False

    def timed_prompts(self) -> bool:
        """Whether a listing carrying a `timeout` and a `default` may run the
        countdown. Off, the fields are dropped before the list is drawn and it
        waits exactly as it does now.

        Concrete and false for the same reason `interactive_lists` is: an
        experiment nothing has turned on must not be turned on by a port that
        forgot to answer.
        """
        return False

    def browser_view(self) -> bool:
        """Whether an action declaring `"view": "browser"` gets the two-pane browser
        instead of a configuration form and a terminal. Off, it runs as an ordinary
        script and its `@dti:` lines are pick-lists or text.

        Concrete and false, for the same reason the other two are: an experiment
        nothing turned on must not be turned on by a port that forgot to answer.
        """
        return False

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
