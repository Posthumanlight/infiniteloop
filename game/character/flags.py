from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True)
class CharacterFlag:
    flag_name: str
    flag_value: JsonValue
    flag_persistence: bool = False

    def __post_init__(self) -> None:
        name = self.flag_name.strip()
        if not name:
            raise ValueError("flag_name cannot be empty")
        _validate_json_value(self.flag_value)
        object.__setattr__(self, "flag_name", name)


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, bool | int | float | str):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("flag_value dict keys must be strings")
            _validate_json_value(item)
        return
    raise ValueError(f"flag_value is not JSON-compatible: {type(value).__name__}")
