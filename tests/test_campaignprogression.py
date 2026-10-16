from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from game import Game
from game.campaignprogression import (
    CAMPAIGN_PERIOD,
    CampaignProgression,
    CampaignProgressionResult,
)
from game.settings.settings import (
    CombatResolutionMethod,
    FastForwardStopCondition,
    Settings,
)
from game.sim import GameUpdateEvents
from game.sim.missionsimulation import MissionSimulation

START = datetime(2000, 1, 1)


@dataclass
class FakeIncomeRecipient:
    accrued_periods: list[int] = field(default_factory=list)

    def accrue_income(self, periods: int = 1) -> float:
        self.accrued_periods.append(periods)
        return float(periods)


def progression_coalitions() -> list[FakeIncomeRecipient]:
    return [FakeIncomeRecipient(), FakeIncomeRecipient()]


def test_progression_does_not_pay_partial_income_period() -> None:
    coalitions = progression_coalitions()
    progression = CampaignProgression.starting_at(START)

    result = progression.advance_to(
        coalitions, START + CAMPAIGN_PERIOD - timedelta(seconds=1)
    )

    assert result.income_periods == 0
    for coalition in coalitions:
        assert coalition.accrued_periods == []


def test_progression_pays_each_completed_income_period() -> None:
    coalitions = progression_coalitions()
    progression = CampaignProgression.starting_at(START)

    first = progression.advance_to(coalitions, START + timedelta(hours=13))
    second = progression.advance_to(coalitions, START + timedelta(hours=18))

    assert first.income_periods == 2
    assert second.income_periods == 1
    for coalition in coalitions:
        assert coalition.accrued_periods == [2, 1]


def test_progression_rejects_time_travel() -> None:
    coalitions = progression_coalitions()
    progression = CampaignProgression.starting_at(START)
    progression.advance_to(coalitions, START + timedelta(hours=1))

    with pytest.raises(ValueError, match="cannot move backwards"):
        progression.advance_to(coalitions, START)

    assert progression.last_update == START + timedelta(hours=1)
    assert progression.income_elapsed == timedelta(hours=1)


def test_synchronize_discards_legacy_partial_period() -> None:
    coalitions = progression_coalitions()
    progression = CampaignProgression.starting_at(START)
    progression.advance_to(coalitions, START + timedelta(hours=5))

    progression.synchronize(START + timedelta(hours=6))
    result = progression.advance_to(coalitions, START + timedelta(hours=7))

    assert result.income_periods == 0
    assert progression.income_elapsed == timedelta(hours=1)


def test_progression_tracks_periodic_ato_replanning() -> None:
    progression = CampaignProgression.starting_at(START)
    interval = timedelta(minutes=15)

    first = progression.advance_to([], START + timedelta(minutes=31), interval)
    second = progression.advance_to([], START + timedelta(minutes=45), interval)

    assert first.ato_replan_periods == 2
    assert second.ato_replan_periods == 1
    assert progression.ato_replan_elapsed == timedelta()


def test_progression_rejects_non_positive_replan_interval() -> None:
    progression = CampaignProgression.starting_at(START)

    with pytest.raises(ValueError, match="must be positive"):
        progression.advance_to([], START, timedelta())


def simulation_game(
    *,
    turnless: bool,
    stop_condition: FastForwardStopCondition = FastForwardStopCondition.DISABLED,
) -> tuple[Game, Mock, Mock, Mock]:
    progression = Mock(spec=CampaignProgression)
    settings = Mock(
        spec=Settings,
        turnless_mode=turnless,
        fast_forward_stop_condition=stop_condition,
        continuous_ato_replan_interval=timedelta(minutes=15),
    )
    blue = Mock()
    red = Mock()
    game: Game = Mock(
        spec=Game,
        simulation_time=START,
        campaign_progression=progression,
        settings=settings,
        blue=blue,
        red=red,
        coalitions=[blue, red],
    )
    return game, progression, blue, red


def test_mission_simulation_advances_campaign_progression_in_turnless_mode() -> None:
    game, progression, _, _ = simulation_game(turnless=True)
    simulation = MissionSimulation(game)

    simulation.tick(GameUpdateEvents(), Mock(), force_continue=False)

    progression.advance_to.assert_called_once_with(
        game.coalitions,
        START + timedelta(seconds=1),
        timedelta(minutes=15),
    )


def test_mission_simulation_preserves_legacy_turn_progression() -> None:
    game, progression, _, _ = simulation_game(turnless=False)
    simulation = MissionSimulation(game)

    simulation.tick(GameUpdateEvents(), Mock(), force_continue=False)

    progression.advance_to.assert_not_called()


@pytest.mark.parametrize("force_continue", [False, True])
def test_mission_simulation_replans_ato_only_during_live_fast_forward(
    force_continue: bool,
) -> None:
    game, progression, blue, red = simulation_game(
        turnless=True,
        stop_condition=FastForwardStopCondition.MANUAL,
    )
    progression.advance_to.return_value = CampaignProgressionResult(
        ato_replan_periods=1
    )
    simulation = MissionSimulation(game)
    events = Mock(spec=GameUpdateEvents, simulation_complete=False)

    with (
        patch.object(simulation.aircraft_simulation, "on_game_tick"),
        patch.object(simulation.control_point_simulation, "on_game_tick"),
    ):
        simulation.tick(
            events,
            CombatResolutionMethod.SKIP,
            force_continue=force_continue,
        )

    if force_continue:
        blue.plan_missions.assert_not_called()
        red.plan_missions.assert_not_called()
        events.begin_new_turn.assert_not_called()
    else:
        blue.plan_missions.assert_called_once_with(START + timedelta(seconds=1))
        red.plan_missions.assert_called_once_with(START + timedelta(seconds=1))
        events.begin_new_turn.assert_called_once_with()


def turn_game(*, turnless: bool) -> tuple[Game, Mock, Mock, Mock]:
    game: Game = object.__new__(Game)
    game.turn = 0
    game.settings = Mock(
        spec=Settings,
        turnless_mode=turnless,
        continuous_ato_replan_interval=timedelta(minutes=15),
    )
    game.blue = Mock()
    game.red = Mock()
    game.theater = Mock(controlpoints=[])
    game.theater.player_points.return_value = []
    game.informations = []
    game.simulation_time = START
    game.campaign_progression = Mock(spec=CampaignProgression)
    return game, game.campaign_progression, game.blue, game.red


def test_turnless_turn_finalization_does_not_duplicate_income() -> None:
    game, progression, blue, red = turn_game(turnless=True)

    game.finish_turn(GameUpdateEvents())

    blue.end_turn.assert_called_once_with(include_income=False)
    red.end_turn.assert_called_once_with(include_income=False)
    progression.advance_to.assert_called_once()
    coalitions, time, interval = progression.advance_to.call_args.args
    assert list(coalitions) == [blue, red]
    assert time == START
    assert interval == timedelta(minutes=15)
    progression.synchronize.assert_not_called()


def test_legacy_turn_finalization_keeps_turn_income() -> None:
    game, progression, blue, red = turn_game(turnless=False)

    game.finish_turn(GameUpdateEvents())

    blue.end_turn.assert_called_once_with(include_income=True)
    red.end_turn.assert_called_once_with(include_income=True)
    progression.advance_to.assert_not_called()
    progression.synchronize.assert_called_once_with(START)
