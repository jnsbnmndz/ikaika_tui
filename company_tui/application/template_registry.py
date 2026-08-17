from collections.abc import Iterable

from company_tui.domain.template_pack import TemplatePack


class TemplatePackRegistry:
    def __init__(self, packs: Iterable[TemplatePack]) -> None:
        self._packs = {item.info.key: item for item in packs}

    def all(self) -> tuple[TemplatePack, ...]:
        return tuple(self._packs.values())

    def get(self, key: str) -> TemplatePack | None:
        return self._packs.get(key)
