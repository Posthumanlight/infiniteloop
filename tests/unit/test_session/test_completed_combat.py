from dataclasses import replace

from game.core.data_loader import clear_cache
from game.core.enums import CombatPhase
from game.session.models import CompletedCombat
from game.session.session_manager import SessionManager

from tests.unit.conftest import make_warrior


def test_finalize_combat_stores_completed_combat_snapshot():
    clear_cache()
    mgr = SessionManager(seed=7)
    state = mgr.start_run("test-session", [make_warrior("p1")])
    state = mgr._node.enter_combat(state, ("goblin",))
    assert state.combat is not None

    defeated_player = replace(state.combat.entities["p1"], current_hp=0)
    combat = replace(
        state.combat,
        phase=CombatPhase.ENDED,
        entities={**state.combat.entities, "p1": defeated_player},
    )
    state = replace(state, combat=combat)

    finalized = mgr._node.finalize_combat(state)

    assert finalized.combat is None
    assert finalized.last_combat is not None
    assert finalized.last_combat.combat_id == combat.combat_id
    assert finalized.last_combat.entities["p1"].current_hp == 0


def test_enter_combat_clears_stale_completed_combat():
    clear_cache()
    mgr = SessionManager(seed=7)
    state = mgr.start_run("test-session", [make_warrior("p1")])
    state = replace(
        state,
        last_combat=CompletedCombat(
            combat_id="old-combat",
            final_round_number=1,
            action_log=(),
            entities={},
        ),
    )

    state = mgr._node.enter_combat(state, ("goblin",))

    assert state.combat is not None
    assert state.last_combat is None
