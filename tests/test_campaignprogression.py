from datetime import datetime, timedelta
from typing import cast
from unittest.mock import Mock, call, patch

import pytest

from game import Game
from game.campaignevents import (
    CampaignEventKind,
    CampaignEventQueue,
    ScheduledCampaignEvent,
)
from game.campaignprogression import (
    CAMPAIGN_PERIOD,
    CampaignProgression,
    CampaignProgressionResult,
    TRANSFER_POLL_INTERVAL,
)
from game.settings.settings import FastForwardStopCondition, Settings
from game.sim import GameUpdateEvents
from game.sim.missionsimulation import MissionSimulation

START = datetime(2000, 1, 1)
ATO_INTERVAL = timedelta(minutes=15)


def event(
    kind: CampaignEventKind,
    due_at: datetime = START,
) -> ScheduledCampaignEvent:
    return ScheduledCampaignEvent(due_at, 0, 0, kind)


def test_progression_does_not_emit_partial_campaign_period() -> None:
    progression = CampaignProgression.starting_at(START)

    result = progression.advance_to(
        START + CAMPAIGN_PERIOD - timedelta(seconds=1),
        ATO_INTERVAL,
    )

    assert result.income_periods == 0
    assert result.count(CampaignEventKind.LOGISTICS) == (
        (CAMPAIGN_PERIOD - timedelta(seconds=1)) // TRANSFER_POLL_INTERVAL
    )
    assert result.count(CampaignEventKind.REPLENISHMENT) == 0
    assert result.count(CampaignEventKind.WEATHER) == 0
    assert result.count(CampaignEventKind.GROUND_COMBAT) > 0
    assert result.count(CampaignEventKind.FRONT_LINE) == 0


def test_progression_emits_each_completed_campaign_period() -> None:
    progression = CampaignProgression.starting_at(START)

    first = progression.advance_to(START + timedelta(hours=13), ATO_INTERVAL)
    second = progression.advance_to(START + timedelta(hours=18), ATO_INTERVAL)

    for kind in (
        CampaignEventKind.REPLENISHMENT,
        CampaignEventKind.INCOME,
        CampaignEventKind.WEATHER,
        CampaignEventKind.FRONT_LINE,
    ):
        assert first.count(kind) == 2
        assert second.count(kind) == 1


def test_progression_rejects_time_travel_without_mutation() -> None:
    progression = CampaignProgression.starting_at(START)
    progression.advance_to(START + timedelta(hours=1), ATO_INTERVAL)
    next_income = progression.event_queue.next_for(CampaignEventKind.INCOME)

    with pytest.raises(ValueError, match="cannot move backwards"):
        progression.advance_to(START, ATO_INTERVAL)

    assert progression.last_update == START + timedelta(hours=1)
    assert progression.event_queue.next_for(CampaignEventKind.INCOME) == next_income


def test_synchronize_restarts_recurring_periods() -> None:
    progression = CampaignProgression.starting_at(START)
    progression.advance_to(START + timedelta(hours=5), ATO_INTERVAL)

    progression.synchronize(START + timedelta(hours=6))
    result = progression.advance_to(START + timedelta(hours=7), ATO_INTERVAL)
    next_income = progression.event_queue.next_for(CampaignEventKind.INCOME)

    assert result.income_periods == 0
    assert next_income is not None
    assert next_income.due_at == START + timedelta(hours=12)


def test_progression_tracks_periodic_ato_replanning() -> None:
    progression = CampaignProgression.starting_at(START)

    first = progression.advance_to(START + timedelta(minutes=31), ATO_INTERVAL)
    second = progression.advance_to(START + timedelta(minutes=45), ATO_INTERVAL)

    assert first.ato_replan_periods == 2
    assert second.ato_replan_periods == 1


def test_progression_rejects_non_positive_replan_interval() -> None:
    progression = CampaignProgression.starting_at(START)

    with pytest.raises(ValueError, match="must be positive"):
        progression.advance_to(START, timedelta())


def test_progression_migrates_15_0_1_accumulators() -> None:
    progression: CampaignProgression = object.__new__(CampaignProgression)
    progression.__setstate__(
        {
            "last_update": START,
            "income_elapsed": timedelta(hours=5),
            "ato_replan_elapsed": timedelta(minutes=10),
        }
    )

    first = progression.advance_to(START + timedelta(minutes=5), ATO_INTERVAL)
    second = progression.advance_to(START + timedelta(hours=1), ATO_INTERVAL)

    assert first.ato_replan_periods == 1
    assert second.income_periods == 1


def test_progression_migrates_15_0_2_logistics_interval() -> None:
    old_queue = CampaignEventQueue()
    old_queue.schedule(
        CampaignEventKind.LOGISTICS,
        START + CAMPAIGN_PERIOD,
        interval=CAMPAIGN_PERIOD,
    )
    progression: CampaignProgression = object.__new__(CampaignProgression)
    progression.__setstate__(
        {
            "last_update": START,
            "event_queue": old_queue,
            "ato_replan_interval": ATO_INTERVAL,
            "_legacy_ato_replan_elapsed": timedelta(),
            "event_schema_version": 1,
        }
    )

    next_logistics = progression.event_queue.next_for(CampaignEventKind.LOGISTICS)
    next_replenishment = progression.event_queue.next_for(
        CampaignEventKind.REPLENISHMENT
    )

    assert next_logistics is not None
    assert next_logistics.due_at == START + TRANSFER_POLL_INTERVAL
    assert next_replenishment is not None
    assert next_replenishment.due_at == START + CAMPAIGN_PERIOD


def test_progression_adds_ground_combat_to_15_0_2_queue() -> None:
    old_queue = CampaignEventQueue()
    progression: CampaignProgression = object.__new__(CampaignProgression)
    progression.__setstate__(
        {
            "last_update": START,
            "event_queue": old_queue,
            "ato_replan_interval": ATO_INTERVAL,
            "_legacy_ato_replan_elapsed": timedelta(),
            "event_schema_version": 2,
        }
    )

    next_combat = progression.event_queue.next_for(CampaignEventKind.GROUND_COMBAT)

    assert next_combat is not None
    assert next_combat.due_at == START + timedelta(minutes=30)


def simulation_game(*, turnless: bool) -> tuple[Game, Mock]:
    settings = Mock(
        spec=Settings,
        turnless_mode=turnless,
        fast_forward_stop_condition=FastForwardStopCondition.DISABLED,
    )
    game: Game = Mock(
        spec=Game,
        simulation_time=START,
        settings=settings,
    )
    return game, cast(Mock, game.advance_campaign_time)


@pytest.mark.parametrize(
    ("turnless", "allow_ato_replan", "expected_calls"),
    [
        (True, True, 1),
        (False, True, 0),
    ],
)
def test_mission_simulation_advances_campaign_time_only_in_turnless_mode(
    turnless: bool,
    allow_ato_replan: bool,
    expected_calls: int,
) -> None:
    game, advance_campaign_time = simulation_game(turnless=turnless)
    simulation = MissionSimulation(game)
    events = GameUpdateEvents()

    simulation.tick(events, Mock(), force_continue=not allow_ato_replan)

    assert advance_campaign_time.call_count == expected_calls
    if expected_calls:
        advance_campaign_time.assert_called_once_with(
            START + timedelta(seconds=1),
            events,
            allow_ato_replan=allow_ato_replan,
            allow_abstract_combat=allow_ato_replan,
        )


def event_game(
    *events: ScheduledCampaignEvent,
) -> tuple[Game, Mock, Mock, Mock]:
    game: Game = object.__new__(Game)
    game.settings = Mock(
        spec=Settings,
        turnless_mode=True,
        continuous_ato_replan_interval=ATO_INTERVAL,
        continuous_ground_combat=True,
    )
    game.campaign_progression = Mock(spec=CampaignProgression)
    game.campaign_progression.advance_to.return_value = CampaignProgressionResult(
        events
    )
    game.blue = Mock()
    game.red = Mock()
    game.theater = Mock()
    return game, game.campaign_progression, game.blue, game.red


@pytest.mark.parametrize("allow_ato_replan", [False, True])
def test_campaign_time_replans_ato_only_when_allowed(
    allow_ato_replan: bool,
) -> None:
    game, progression, blue, red = event_game(event(CampaignEventKind.ATO_REPLAN))
    events = Mock(spec=GameUpdateEvents)

    game.advance_campaign_time(
        START,
        events,
        allow_ato_replan=allow_ato_replan,
        allow_abstract_combat=allow_ato_replan,
    )

    progression.advance_to.assert_called_once_with(START, ATO_INTERVAL)
    if allow_ato_replan:
        blue.plan_missions.assert_called_once_with(START)
        red.plan_missions.assert_called_once_with(START)
        events.begin_new_turn.assert_called_once_with()
    else:
        blue.plan_missions.assert_not_called()
        red.plan_missions.assert_not_called()
        events.begin_new_turn.assert_not_called()


def test_campaign_time_dispatches_income_and_weather() -> None:
    weather_time = START + CAMPAIGN_PERIOD
    game, _, blue, red = event_game(
        event(CampaignEventKind.INCOME, weather_time),
        event(CampaignEventKind.WEATHER, weather_time),
    )
    expected_conditions = Mock()

    with patch.object(
        game,
        "generate_conditions_at",
        return_value=expected_conditions,
    ) as generate_conditions_at:
        game.advance_campaign_time(
            weather_time,
            Mock(spec=GameUpdateEvents),
            allow_ato_replan=True,
            allow_abstract_combat=True,
        )

    blue.accrue_income.assert_called_once_with()
    red.accrue_income.assert_called_once_with()
    generate_conditions_at.assert_called_once_with(weather_time)
    assert game.conditions is expected_conditions


@pytest.mark.parametrize("allow_abstract_combat", [False, True])
def test_campaign_time_avoids_double_counting_dcs_ground_combat(
    allow_abstract_combat: bool,
) -> None:
    front_line = Mock()
    game, _, _, _ = event_game(event(CampaignEventKind.GROUND_COMBAT))
    conflicts = cast(Mock, game.theater.conflicts)
    conflicts.return_value = [front_line]
    game.continuous_ground_war = Mock()
    events = Mock(spec=GameUpdateEvents)

    game.advance_campaign_time(
        START,
        events,
        allow_ato_replan=False,
        allow_abstract_combat=allow_abstract_combat,
    )

    if allow_abstract_combat:
        game.continuous_ground_war.resolve.assert_called_once_with(front_line)
        front_line.update_position.assert_called_once_with()
        events.update_front_line.assert_called_once_with(front_line)
        assert events.update_control_point.call_args_list == [
            call(front_line.blue_cp),
            call(front_line.red_cp),
        ]
    else:
        game.continuous_ground_war.resolve.assert_not_called()


def test_continuous_transfers_preserve_dependency_order() -> None:
    game, _, blue, red = event_game()
    calls: list[str] = []

    blue.update_transit_network.side_effect = lambda: calls.append("blue-network")
    blue.transfers.perform_transfers.side_effect = lambda time: calls.append(
        "blue-transfer"
    )
    red.update_transit_network.side_effect = lambda: calls.append("red-network")
    red.transfers.perform_transfers.side_effect = lambda time: calls.append(
        "red-transfer"
    )
    blue.transfers.plan_transports.side_effect = lambda time: calls.append(
        "blue-planning"
    )
    red.transfers.plan_transports.side_effect = lambda time: calls.append(
        "red-planning"
    )

    game._process_continuous_transfers(START)

    assert calls == [
        "blue-network",
        "blue-transfer",
        "blue-planning",
        "red-network",
        "red-transfer",
        "red-planning",
    ]


def test_periodic_replenishment_processes_orders_before_air_wings() -> None:
    game, _, blue, red = event_game()
    control_point = Mock()
    game.theater.controlpoints = [control_point]
    calls: list[str] = []
    control_point.ground_unit_orders.process.side_effect = (
        lambda game, time: calls.append("ground-orders")
    )
    blue.air_wing.process_periodic_replenishment.side_effect = lambda: calls.append(
        "blue-replenishment"
    )
    red.air_wing.process_periodic_replenishment.side_effect = lambda: calls.append(
        "red-replenishment"
    )

    game._process_periodic_replenishment(START)

    assert calls == [
        "ground-orders",
        "blue-replenishment",
        "red-replenishment",
    ]


def test_turnless_calendar_uses_simulation_time() -> None:
    game: Game = object.__new__(Game)
    game.settings = Mock(spec=Settings, turnless_mode=True)
    game.simulation_time = datetime(2001, 2, 3, 14, 30)
    game.theater = Mock()

    with patch(
        "game.game.from_datetime",
        return_value=Mock(),
    ) as time_of_day:
        assert game.current_day == game.simulation_time.date()
        assert game.current_turn_time_of_day is time_of_day.return_value

    time_of_day.assert_called_once_with(
        game.simulation_time,
        game.theater.terrain,
    )


def turn_game(*, turnless: bool) -> tuple[Game, Mock, Mock, Mock]:
    game: Game = object.__new__(Game)
    game.turn = 0
    game.settings = Mock(spec=Settings, turnless_mode=turnless)
    game.blue = Mock()
    game.red = Mock()
    game.theater = Mock(controlpoints=[])
    game.theater.player_points.return_value = []
    game.informations = []
    game.simulation_time = START
    game.campaign_progression = Mock(spec=CampaignProgression)
    return game, game.campaign_progression, game.blue, game.red


def test_turnless_turn_finalization_does_not_duplicate_periodic_events() -> None:
    game, progression, blue, red = turn_game(turnless=True)

    game.finish_turn(GameUpdateEvents())

    blue.end_turn.assert_called_once_with(
        include_income=False,
        include_periodic_systems=False,
    )
    red.end_turn.assert_called_once_with(
        include_income=False,
        include_periodic_systems=False,
    )
    progression.synchronize.assert_not_called()


def test_legacy_turn_finalization_keeps_periodic_systems() -> None:
    game, progression, blue, red = turn_game(turnless=False)

    game.finish_turn(GameUpdateEvents())

    blue.end_turn.assert_called_once_with(
        include_income=True,
        include_periodic_systems=True,
    )
    red.end_turn.assert_called_once_with(
        include_income=True,
        include_periodic_systems=True,
    )
    progression.synchronize.assert_called_once_with(START)
