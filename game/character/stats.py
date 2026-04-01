from dataclasses import dataclass

from game.core.enums import DamageType


@dataclass(frozen=True)
class MajorStats:
    attack: int
    hp: int
    speed: int
    crit_chance: float
    crit_dmg: float
    resistance: int
    energy: int
    mastery: int


@dataclass(frozen=True)
class MinorStats:
    values: dict[str, float]

    def get_dmg_pct(self, damage_type: DamageType) -> float:
        return self.values.get(f"{damage_type.value}_dmg_pct", 0.0)

    def get_def_pct(self, damage_type: DamageType) -> float:
        return self.values.get(f"{damage_type.value}_def_pct", 0.0)

    def with_value(self, key: str, val: float) -> "MinorStats":
        return MinorStats(values={**self.values, key: val})
