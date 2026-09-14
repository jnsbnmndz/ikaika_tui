"""The Expo half of a React Native project's identity."""

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

        json_document.discard(document, EAS_PROJECT_ID)

        return json_document.dump(document, json_document.detect_indent(source))

    return rewrite
