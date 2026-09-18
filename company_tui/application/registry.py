"""The capabilities, in the order the menu numbers them."""

from collections.abc import Iterable

from company_tui.domain.capability import Capability
from company_tui.domain.layout import Menu, arrange


class CapabilityRegistry:
    def __init__(
        self, capabilities: Iterable[Capability], menu: Menu | None = None
    ) -> None:
        self._capabilities = {item.info.key: item for item in capabilities}
        self._menu = menu if menu is not None else Menu()

    def all(self) -> tuple[Capability, ...]:
        """What the menu shows, in the order it shows it.

        Registration order unless a layout says otherwise, because the numbers
        people have learned follow it.
        """
        return tuple(
            self._capabilities[key]
            for key in arrange(tuple(self._capabilities), self._menu)
        )

    def every(self) -> tuple[Capability, ...]:
        """All of them, registration order, including any left off the menu."""
        return tuple(self._capabilities.values())

    def get(self, key: str) -> Capability | None:
        """By key, whether or not the menu shows it: off the menu is not gone, and
        `--start` naming a hidden capability still opens it."""
        return self._capabilities.get(key)
