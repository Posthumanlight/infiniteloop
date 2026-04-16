import re

from game.core.data_loader import LocationOption
from game.core.enums import CombatLocationType, LocationType

_GENERIC_COMBAT_NAME_RE = re.compile(r"^Combat \d+$")

_COMBAT_TYPE_LABELS: dict[CombatLocationType, str] = {
    CombatLocationType.NORMAL: "Normal",
    CombatLocationType.ELITE: "Elite",
    CombatLocationType.SWARM: "Swarm",
    CombatLocationType.SOLO_BOSS: "Solo Boss",
    CombatLocationType.BOSS_GROUP: "Boss Group",
}


def combat_type_label(combat_type: CombatLocationType) -> str:
    return _COMBAT_TYPE_LABELS[combat_type]


def location_display_label(opt: LocationOption) -> str:
    if opt.location_type != LocationType.COMBAT or opt.combat_type is None:
        return opt.name

    type_label = combat_type_label(opt.combat_type)
    if _GENERIC_COMBAT_NAME_RE.match(opt.name):
        return type_label

    return f"{type_label} - {opt.name}"
