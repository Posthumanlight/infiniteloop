from dataclasses import dataclass, field, replace

from game.character.base_entity import BaseEntity
from game.character.flags import CharacterFlag, JsonValue
from game.character.inventory import Inventory


@dataclass(frozen=True)
class PlayerCharacter(BaseEntity):
    player_class: str = ""
    skills: tuple[str, ...] = ()
    inventory: Inventory = None  # type: ignore[assignment] — caller must provide
    level: int = 1
    xp: int = 0
    flags: dict[str, CharacterFlag] = field(default_factory=dict)

    def apply_flag(
        self,
        flag_name: str,
        flag_value: JsonValue,
        *,
        flag_persistence: bool = False,
    ) -> "PlayerCharacter":
        flag = CharacterFlag(
            flag_name=flag_name,
            flag_value=flag_value,
            flag_persistence=flag_persistence,
        )
        return replace(self, flags={**self.flags, flag.flag_name: flag})

    def remove_flag(self, flag_name: str) -> "PlayerCharacter":
        normalized = flag_name.strip()
        if normalized not in self.flags:
            return self
        flags = dict(self.flags)
        flags.pop(normalized)
        return replace(self, flags=flags)
