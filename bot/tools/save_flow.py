from __future__ import annotations

from dataclasses import dataclass, field

from game_service import GameService


@dataclass
class PendingSaveChoice:
    entity_id: str
    tg_user_id: int
    display_name: str
    class_id: str
    source_character_id: int | None = None
    source_character_name: str | None = None
    wants_save: bool | None = None
    awaiting_name: bool = False
    resolved: bool = False

    @property
    def is_transient(self) -> bool:
        return self.source_character_id is None


@dataclass
class SessionSaveFlow:
    session_id: str
    choices: dict[str, PendingSaveChoice] = field(default_factory=dict)

    def all_resolved(self) -> bool:
        return bool(self.choices) and all(choice.resolved for choice in self.choices.values())

    def choice_for_user(self, tg_user_id: int) -> PendingSaveChoice | None:
        for choice in self.choices.values():
            if choice.tg_user_id == tg_user_id:
                return choice
        return None


_SAVE_FLOWS: dict[str, SessionSaveFlow] = {}


def get_save_flow(session_id: str) -> SessionSaveFlow | None:
    return _SAVE_FLOWS.get(session_id)


def clear_save_flow(session_id: str) -> None:
    _SAVE_FLOWS.pop(session_id, None)


def start_save_flow(
    game_service: GameService,
    session_id: str,
) -> SessionSaveFlow:
    existing = _SAVE_FLOWS.get(session_id)
    if existing is not None:
        return existing

    session = game_service._get_session(session_id)
    origins = session.save_origins or {}
    choices: dict[str, PendingSaveChoice] = {}
    for entity_id, info in session.players.items():
        origin = origins.get(entity_id)
        class_id = info.class_id or "unknown"
        source_character_id = getattr(origin, "character_id", None)
        source_character_name = getattr(origin, "character_name", None)
        choices[entity_id] = PendingSaveChoice(
            entity_id=entity_id,
            tg_user_id=info.tg_user_id,
            display_name=info.display_name,
            class_id=class_id,
            source_character_id=source_character_id,
            source_character_name=source_character_name,
        )

    flow = SessionSaveFlow(session_id=session_id, choices=choices)
    _SAVE_FLOWS[session_id] = flow
    return flow
