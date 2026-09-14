"""No presentation class may shadow a Textual base method with a different signature."""

import importlib
import inspect
import pkgutil
import unittest

import company_tui.presentation as presentation


def _presentation_classes():
    for info in pkgutil.iter_modules(presentation.__path__):
        module = importlib.import_module(f"company_tui.presentation.{info.name}")
        for name, value in vars(module).items():
            if inspect.isclass(value) and value.__module__ == module.__name__:
                yield module.__name__, name, value


def _clashes(cls):
    """Methods that override something in the MRO with different parameters."""
    found = []
    for name, function in vars(cls).items():
        if not inspect.isfunction(function) or name == "__init__":
            continue
        for base in cls.__mro__[1:]:
            if name not in vars(base):
                continue
            inherited = vars(base)[name]
            if inspect.isfunction(inherited):
                ours = list(inspect.signature(function).parameters)
                theirs = list(inspect.signature(inherited).parameters)
                if ours != theirs:
                    found.append((name, f"{base.__module__}.{base.__name__}", ours, theirs))
            break
    return found


class NothingShadowsTextual(unittest.TestCase):
    """`TuiConsole._attach(session)` silently overrode `MessagePump._attach(parent)`.

    Textual calls `_attach`/`_detach` on widgets as it mounts and unmounts them. The app
    is the root and is never attached to a parent, so it never fired - but a private
    helper sitting on a base method's name is one version away from being called with a
    `MessagePump` where it expects a `RunSession`. `_detach` was worse: same signature,
    so no checker could see it at all.
    """

    def test_no_presentation_class_shadows_a_base_method(self):
        offenders = []
        for module, name, cls in _presentation_classes():
            for method, base, ours, theirs in _clashes(cls):
                offenders.append(
                    f"{module}.{name}.{method}{tuple(ours)} "
                    f"overrides {base}.{method}{tuple(theirs)}"
                )
        self.assertEqual([], offenders, "rename the helper; the base name is not ours")

    def test_the_walk_finds_classes_at_all(self):
        names = [name for _, name, _ in _presentation_classes()]
        self.assertIn("TuiConsole", names)
        self.assertGreater(len(names), 20)

    def test_the_detector_still_catches_one(self):
        """A check of the form "nothing does X" needs X to still be detectable."""
        from textual.widget import Widget

        class Offender(Widget):
            def render(self, extra):
                return extra

        self.assertTrue(_clashes(Offender), "the detector has stopped detecting")
