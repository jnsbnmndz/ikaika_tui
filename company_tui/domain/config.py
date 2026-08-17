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

DEFAULT_BUNDLE_PREFIX = "com.ikaika"
DEFAULT_WORKSPACE_ROOT = "."


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


class ConfigPort(ABC):
    @abstractmethod
    def template_source(self, pack_key: str, default: TemplateSource) -> TemplateSource:
        """Where `pack_key` clones from, falling back to what the pack ships with."""
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
