from unittest.mock import Mock

from game.commander.tasks.compound.attackbuildings import AttackBuildings
from game.commander.tasks.compound.degradeiads import DegradeIads
from game.commander.tasks.compound.nextaction import PlanNextAction
from game.commander.tasks.compound.protectairspace import ProtectAirSpace
from game.commander.tasks.compound.theatersupport import TheaterSupport
from game.commander.theaterstate import TheaterState
from game.settings import Settings


def state_with_priorities(**overrides: int) -> TheaterState:
    settings = Settings()
    for name, value in overrides.items():
        setattr(settings, name, value)
    state = Mock(
        spec=TheaterState,
        context=Mock(settings=settings),
    )
    return state


def planned_task_types(state: TheaterState) -> list[type]:
    methods = PlanNextAction(aircraft_cold_start=True).each_valid_method(state)
    return [type(method[0]) for method in methods]


def test_default_priorities_preserve_legacy_order() -> None:
    tasks = planned_task_types(state_with_priorities())

    assert tasks[0] is TheaterSupport
    assert tasks[1] is ProtectAirSpace
    assert tasks[-1] is DegradeIads


def test_player_priority_reorders_commander_actions() -> None:
    tasks = planned_task_types(
        state_with_priorities(
            priority_strike=100,
            priority_theater_support=10,
        )
    )

    assert tasks[0] is AttackBuildings


def test_zero_priority_disables_action_category() -> None:
    tasks = planned_task_types(
        state_with_priorities(
            priority_iads=0,
        )
    )

    assert DegradeIads not in tasks
