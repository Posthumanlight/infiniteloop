from dataclasses import replace

from game.combat.models import ActionRequest, ActionResult
from game.core.enums import ActionType, SessionPhase
from game.session.models import ActiveSession, CompletedCombat, SessionState
from game_service import GameService

from tests.unit.conftest import make_goblin, make_warrior


class _Provider:
    def __init__(self, session: ActiveSession) -> None:
        self.session = session

    def has_active_session(self, session_id: str) -> bool:
        return True

    def get_active_session(self, session_id: str) -> ActiveSession:
        return self.session

    def get_session_players(self, session_id: str):
        return list(self.session.players.values())


def _action(actor_id: str, target_id: str, round_number: int) -> ActionResult:
    return ActionResult(
        actor_id=actor_id,
        action=ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id="slash",
            target_ids=((0, target_id),),
        ),
        round_number=round_number,
    )


def test_ended_turn_batch_uses_whole_final_round_and_completed_entities():
    player = make_warrior("p1")
    enemy = replace(make_goblin("e1"), current_hp=0)
    completed = CompletedCombat(
        combat_id="combat-1",
        final_round_number=2,
        action_log=(
            _action("p1", "e1", 1),
            _action("e1", "p1", 2),
            _action("p1", "e1", 2),
        ),
        entities={
            "p1": player,
            "e1": enemy,
        },
    )
    session = ActiveSession(
        session_id="session-1",
        players={},
        manager=object(),
        state=SessionState(
            session_id="session-1",
            players=(player,),
            phase=SessionPhase.EXPLORING,
            last_combat=completed,
        ),
    )
    service = GameService(_Provider(session))

    batch = service._build_turn_batch(session, ())

    assert batch.combat_ended is True
    assert batch.whose_turn is None
    assert [result.actor_id for result in batch.results] == ["e1", "p1"]
    assert "e1" in batch.entities
    assert batch.entities["e1"].is_alive is False
