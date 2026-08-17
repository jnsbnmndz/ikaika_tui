"""The Expo half of a React Native project's identity.

`app.json` is not part of the IKAIKA project contract — only this stack has one
— so the mapping from a project name onto Expo's fields lives with the stack
that owns the file rather than in the finalizer every stack shares.

Expo spells the same name four ways, and each one has to be right or the
consequence is silent: a slug that still says `react-native-structure` publishes
over the template's project, and a scheme shared with another app means the
wrong one opens the link.
"""

from collections.abc import Callable

from company_tui.domain import json_document
from company_tui.domain.identity import ProjectIdentity
from company_tui.domain.json_document import MalformedJson

APP_MANIFEST = "app.json"

EXPO = ("expo",)
NAME = ("expo", "name")
SLUG = ("expo", "slug")
SCHEME = ("expo", "scheme")
IOS_BUNDLE_ID = ("expo", "ios", "bundleIdentifier")
ANDROID_PACKAGE = ("expo", "android", "package")
EAS_PROJECT_ID = ("expo", "extra", "eas", "projectId")


def rewriter(bundle_prefix: str) -> Callable[[str, ProjectIdentity], str]:
    """An `app.json` rewrite bound to the organisation's bundle prefix."""

    def rewrite(source: str, identity: ProjectIdentity) -> str:
        document = json_document.load(source)
        if not isinstance(json_document.read(document, EXPO), dict):
            raise MalformedJson(f"{APP_MANIFEST} has no 'expo' section.")

        identifier = f"{bundle_prefix}.{identity.name.compact}"
        json_document.put(document, NAME, identity.name.raw)
        json_document.put(document, SLUG, identity.name.slug)
        json_document.put(document, SCHEME, identity.name.compact)
        json_document.put(document, IOS_BUNDLE_ID, identifier)
        json_document.put(document, ANDROID_PACKAGE, identifier)

        # The template's EAS project belongs to the template. Left in place, every
        # project scaffolded from it would build into the same one, and the first
        # anybody would know is a build appearing under the wrong app.
        json_document.discard(document, EAS_PROJECT_ID)

        return json_document.dump(document, json_document.detect_indent(source))

    return rewrite
