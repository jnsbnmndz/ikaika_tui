"""One-line detail shown under the cards for whichever entry has focus.

Card descriptions have to stay short enough to fit a card; these do not, so the
menu can say more about the focused entry without crowding the grid.
"""

_HINTS = {
    "scaffold": "Start a new project, or add a controller to one you already have.",
    "build": "Run the build for the stack you pick, in the current directory.",
    "deploy": "Ship the current project through a configured deployment workflow.",
    "scripts": "Discover and run the automation commands defined by this project.",
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
