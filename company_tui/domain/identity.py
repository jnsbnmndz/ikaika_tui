"""What a project is called, and the one file that records it."""

from dataclasses import dataclass

from company_tui.domain import json_document, naming
from company_tui.domain.project_name import ProjectName

SCRIPT_MANIFEST = naming.SCRIPT_MANIFEST
MANIFEST_INDENT = "    "
REQUIRED_KEYS = ("version", "name", "description", "title")
DEFAULT_VERSION = "0.0.0+1"


class NotAProjectError(Exception):
    """No script manifest here, so nothing about this tree is safe to assume."""

class MalformedScriptManifest(Exception):
    """There is a manifest, but it does not carry the keys every project has."""

@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    name: ProjectName
    title: str
    description: str
    version: str = DEFAULT_VERSION

    @classmethod
    def derive(
        cls,
        name: ProjectName,
        *,
        title: str = "",
        description: str = "",
        version: str = DEFAULT_VERSION,
    ) -> "ProjectIdentity":
        """Fill in what the user did not type, from what they did."""
        resolved_title = title.strip() or name.title
        return cls(
            name=name,
            title=resolved_title,
            description=description.strip() or f"A {resolved_title} project",
            version=version.strip() or DEFAULT_VERSION,
        )

    def as_manifest(self) -> dict[str, str]:
        return {
            "version": self.version,
            "name": self.name.slug,
            "description": self.description,
            "title": self.title,
        }


def new_manifest(identity: ProjectIdentity) -> str:
    """The manifest for a project being written from nothing."""
    return json_document.dump(identity.as_manifest(), MANIFEST_INDENT)


def apply_identity(source: str, identity: ProjectIdentity) -> str:
    """Stamp `identity` onto an existing manifest, keeping the rest of it."""
    document = json_document.load(source)
    absent = tuple(key for key in REQUIRED_KEYS if key not in document)
    if absent:
        raise MalformedScriptManifest(
            f"{SCRIPT_MANIFEST} is missing {', '.join(absent)}."
        )
    document.update(identity.as_manifest())
    return json_document.dump(document, json_document.detect_indent(source))


def read_identity(source: str) -> ProjectIdentity:
    """The identity a project already claims, for the generators to work from."""
    document = json_document.load(source)
    absent = tuple(key for key in REQUIRED_KEYS if key not in document)
    if absent:
        raise MalformedScriptManifest(
            f"{SCRIPT_MANIFEST} is missing {', '.join(absent)}."
        )
    return ProjectIdentity(
        name=ProjectName.existing(str(document["name"])),
        title=str(document["title"]),
        description=str(document["description"]),
        version=str(document["version"]),
    )
