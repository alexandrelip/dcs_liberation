from datetime import datetime
from unittest.mock import Mock, patch

from game.ato import FlightType
from game.ato.airtaaskingorder import AirTaskingOrder
from game.coalition import Coalition
from game.commander.reactiveato import QRA_RANGE, ReactiveAto
from game.game import Game
from game.sim import GameUpdateEvents
from game.theater import TheaterGroundObject


def package(
    *,
    player: bool = True,
    task: FlightType = FlightType.STRIKE,
    target: Mock | TheaterGroundObject | None = None,
    waiting: bool = True,
    is_helo: bool = False,
    runway_operational: bool = True,
) -> tuple[Mock, Mock]:
    if target is None:
        target = Mock()
        target.is_friendly.return_value = not player
    departure = Mock(captured=player)
    departure.runway_is_operational.return_value = runway_operational
    flight = Mock(departure=departure, is_helo=is_helo)
    mission = Mock(
        flights=[flight],
        target=target,
        primary_task=task,
    )
    mission.all_flights_waiting_for_start.return_value = waiting
    return mission, flight


def test_destroyed_target_package_is_pruned() -> None:
    target = Mock(spec=TheaterGroundObject, is_dead=True)
    mission, _ = package(target=target)
    coalition = Mock(player=True, ato=AirTaskingOrder([mission]))
    events = Mock(spec=GameUpdateEvents)

    game = Mock(spec=Game)
    with patch.object(
        ReactiveAto,
        "threatened_control_points",
        return_value=[],
    ):
        cancelled = ReactiveAto.prune_invalid_packages(game, coalition, events)

    assert len(cancelled) == 1
    assert not coalition.ato.packages
    events.delete_flights_in_package.assert_called_once_with(mission)


def test_in_progress_package_is_never_pruned() -> None:
    mission, _ = package(waiting=False)
    coalition = Mock(player=True, ato=AirTaskingOrder([mission]))

    game = Mock(spec=Game)
    with patch.object(
        ReactiveAto,
        "threatened_control_points",
        return_value=[],
    ):
        cancelled = ReactiveAto.prune_invalid_packages(
            game,
            coalition,
            Mock(spec=GameUpdateEvents),
        )

    assert cancelled == []
    assert coalition.ato.packages == [mission]


def test_captured_departure_invalidates_unlaunched_package() -> None:
    mission, flight = package()
    flight.departure.captured = False

    reason = ReactiveAto.invalid_reason(mission, player=True)

    assert reason is not None
    assert "changed ownership" in reason


def test_damaged_runway_invalidates_fixed_wing_but_not_helicopter() -> None:
    fixed_wing, _ = package(runway_operational=False)
    helicopter, _ = package(runway_operational=False, is_helo=True)

    assert ReactiveAto.invalid_reason(fixed_wing, player=True) is not None
    assert ReactiveAto.invalid_reason(helicopter, player=True) is None


def test_offensive_package_is_invalid_when_target_becomes_friendly() -> None:
    target = Mock()
    target.is_friendly.return_value = True
    mission, _ = package(target=target)

    reason = ReactiveAto.invalid_reason(mission, player=True)

    assert reason is not None
    assert "now friendly" in reason


def test_support_package_is_invalid_when_destination_is_lost() -> None:
    target = Mock()
    target.is_friendly.return_value = False
    mission, _ = package(task=FlightType.REFUELING, target=target)

    reason = ReactiveAto.invalid_reason(mission, player=True)

    assert reason is not None
    assert "no longer friendly" in reason


def qra_game(*, hostile_distance: float) -> tuple[Game, Coalition, Mock]:
    hostile_position = Mock()
    hostile_flight = Mock(alive=True)
    hostile_flight.state.in_flight = True
    hostile_flight.position.return_value = hostile_position
    hostile_package = Mock(flights=[hostile_flight])
    opponent = Mock()
    opponent.ato.packages = [hostile_package]
    coalition = Mock(spec=Coalition, player=True, opponent=opponent)
    coalition.ato = AirTaskingOrder()
    control_point = Mock()
    control_point.runway_is_operational.return_value = True
    control_point.position.distance_to_point.return_value = hostile_distance
    game = Mock(
        spec=Game,
        theater=Mock(),
        db=Mock(),
        settings=Mock(),
    )
    game.theater.control_points_for.return_value = [control_point]
    return game, coalition, control_point


def test_qra_detects_hostile_flight_within_range() -> None:
    game, coalition, control_point = qra_game(hostile_distance=QRA_RANGE.meters - 1)

    threatened = ReactiveAto.threatened_control_points(game, coalition)

    assert threatened == [control_point]


def test_qra_ignores_hostile_flight_outside_range() -> None:
    game, coalition, _ = qra_game(hostile_distance=QRA_RANGE.meters + 1)

    assert ReactiveAto.threatened_control_points(game, coalition) == []


def test_qra_plans_single_interception_package() -> None:
    game, coalition, control_point = qra_game(hostile_distance=0)
    planned_package = Mock(
        target=control_point,
        primary_task=FlightType.INTERCEPTION,
    )
    fulfiller = Mock()
    fulfiller.plan_mission.return_value = planned_package
    now = datetime(2000, 1, 1)

    with patch(
        "game.commander.reactiveato.PackageFulfiller",
        return_value=fulfiller,
    ):
        planned = ReactiveAto.plan_interceptions(game, coalition, now)

    assert planned == [planned_package]
    planned_package.set_tot_asap.assert_called_once_with(now)
    mission = fulfiller.plan_mission.call_args.args[0]
    assert mission.location is control_point
    assert mission.flights[0].task is FlightType.INTERCEPTION


def test_qra_does_not_duplicate_existing_interception() -> None:
    game, coalition, control_point = qra_game(hostile_distance=0)
    coalition.ato.packages = [
        Mock(
            target=control_point,
            primary_task=FlightType.INTERCEPTION,
        )
    ]

    planned = ReactiveAto.plan_interceptions(
        game,
        coalition,
        datetime(2000, 1, 1),
    )

    assert planned == []


def test_stale_unlaunched_qra_is_pruned() -> None:
    game, coalition, control_point = qra_game(hostile_distance=QRA_RANGE.meters + 1)
    mission, _ = package(
        task=FlightType.INTERCEPTION,
        target=control_point,
    )
    coalition.ato.packages = [mission]

    cancelled = ReactiveAto.prune_invalid_packages(
        game,
        coalition,
        Mock(spec=GameUpdateEvents),
    )

    assert len(cancelled) == 1
    assert "no hostile aircraft" in cancelled[0].reason
