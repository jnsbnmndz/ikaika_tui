"""One-line detail shown under the cards for whichever entry has focus.

Card descriptions have to stay short enough to fit a card; these do not, so the
menu can say more about the focused entry without crowding the grid.
"""

_HINTS = {
    "scaffold": "Start a new project, or add a file to one you already have.",
    "build": "Run a workflow from the stack's script repository against a project.",
    "deploy": "Ship the current project through a configured deployment workflow.",
    "scripts": "Discover and run the automation commands defined by this project.",
    # Sections of a project's own script config. Keyed by the domain names the
    # IKAIKA PowerShell toolkit emits; a document using any other name falls
    # through to the card's own description, which is what the fallback is for.
    "commands": "This project's own commands, which override any of the same name.",
    "git": "Branches, tags, and the checks that run before a push.",
    "windows": "Code signing and the certificates an installer is signed with.",
    "dotnet": "Build a .NET application and report where it landed.",
    "navisworks": "The Navisworks host add-in and the model workspace.",
    "toolkit": "Release this tooling, or move this project onto a version of it.",
    "php": "Deploy a PHP backend and version the plugin it ships as.",
    "flutter": "Build, run and deploy a Flutter application.",
    "react-native": "Build and run a React Native application.",
    "settings": "Edit ikaika.toml — workspace, bundle prefix, and template sources.",
    "doctor": "Report the interpreter, the platform, and the tools each stack needs.",
    "new_project": "Write a fresh project tree from a versioned template pack.",
    "controller": "Add screens, components and services to the project you are in.",
    "python": "Reference pack — writes a real, runnable project tree.",
    "flutter": "Mobile, desktop, and web from one Dart codebase.",
    "react": "Web front end built on the React component model.",
    "react_native": "Native Android and iOS apps built with React components.",
    "skeleton": "Copy-paste starting point for a stack that has no pack yet.",
}


def hint_for(key: str, fallback: str) -> str:
    return _HINTS.get(key, fallback)
