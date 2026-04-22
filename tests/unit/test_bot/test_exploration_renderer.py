from game.core.enums import EventPhase, EventType
from game.core.game_models import PlayerInfo
from game.events.models import ChoiceDef, EventDef, EventStageDef, EventState, Vote
from bot.tools.exploration_renderer import render_event


def test_render_event_uses_current_stage_title_description_and_choices():
    event_def = EventDef(
        event_id="demon_bargain",
        name="Demon Bargain",
        event_type=EventType.MULTIPLAYER,
        initial_stage_id="start",
        stages={
            "start": EventStageDef(
                stage_id="start",
                title="The Offer",
                description="A first offer.",
                choices=(
                    ChoiceDef(
                        index=0,
                        label="Ask the price",
                        description="Continue.",
                        next_stage="price",
                    ),
                ),
            ),
            "price": EventStageDef(
                stage_id="price",
                title="The Price",
                description="The demon names the price.",
                choices=(
                    ChoiceDef(
                        index=0,
                        label="Accept",
                        description="Take the deal.",
                    ),
                    ChoiceDef(
                        index=1,
                        label="Refuse",
                        description="Walk away.",
                    ),
                ),
            ),
        },
    )
    state = EventState(
        event_id="event-instance",
        session_id="session",
        event_def=event_def,
        phase=EventPhase.PRESENTING,
        player_ids=("p1", "p2"),
        current_stage_id="price",
        votes=(Vote(player_id="p1", choice_index=1),),
    )
    players = {
        "p1": PlayerInfo("p1", 1, "Ada"),
        "p2": PlayerInfo("p2", 2, "Ben"),
    }

    text = render_event(state, players)

    assert "Demon Bargain - The Price" in text
    assert "The demon names the price." in text
    assert "Ask the price" not in text
    assert "Accept [0 votes]" in text
    assert "Refuse [1 votes]" in text
    assert "Waiting for: Ben" in text
