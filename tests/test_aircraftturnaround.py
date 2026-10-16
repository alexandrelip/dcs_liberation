from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from game import Game
from game.ato.flight import Flight
from game.ato.flightplans.airlift import AirliftFlightPlan
from game.ato.flightstate import Completed
from game.settings import Settings
from game.settings.settings import CombatResolutionMethod
from game.sim import GameUpdateEvents
from game.sim.aircraftsimulation import AircraftSimulation
from game.squadrons.squadron import Squadron

NOW = datetime(2000, 1, 1)


def squadron_with_inventory(*, owned: int = 4, untasked: int = 1) -> Squadron:
    squadron: Squadron = object.__new__(Squadron)
    squadron.name = "Test Squadron"
    squadron.owned_aircraft = owned
    squadron.untasked_aircraft = untasked
    squadron.aircraft_in_turnaround = []
    return squadron


def test_returned_aircraft_remain_unavailable_until_ready() -> None:
    squadron = squadron_with_inventory()
    ready_at = NOW + timedelta(hours=1)

    squadron.return_aircraft(2, ready_at)

    assert squadron.untasked_aircraft == 1
    assert squadron.release_ready_aircraft(ready_at - timedelta(seconds=1)) == 0
    assert squadron.untasked_aircraft == 1
    assert squadron.release_ready_aircraft(ready_at) == 2
    assert squadron.untasked_aircraft == 3
    assert squadron.aircraft_in_turnaround == []


def test_aircraft_can_be_returned_immediately() -> None:
    squadron = squadron_with_inventory()

    squadron.return_aircraft(2)

    assert squadron.untasked_aircraft == 3
    assert squadron.aircraft_in_turnaround == []


def test_aircraft_cannot_be_returned_twice() -> None:
    squadron = squadron_with_inventory(owned=2, untasked=1)

    with pytest.raises(ValueError, match="Only 1 are currently assigned"):
        squadron.return_aircraft(2)


def test_reset_clears_turnaround_state() -> None:
    squadron = squadron_with_inventory(owned=4, untasked=1)
    squadron.aircraft_in_turnaround = [NOW + timedelta(hours=1)]
    squadron.current_roster = []

    squadron.return_all_pilots_and_aircraft()

    assert squadron.untasked_aircraft == 4
    assert squadron.aircraft_in_turnaround == []


def test_turnless_reset_preserves_turnaround_state() -> None:
    squadron = squadron_with_inventory(owned=4, untasked=1)
    ready_at = NOW + timedelta(hours=1)
    squadron.aircraft_in_turnaround = [ready_at]
    squadron.current_roster = []

    squadron.return_all_pilots_and_aircraft(preserve_turnaround=True)

    assert squadron.untasked_aircraft == 3
    assert squadron.aircraft_in_turnaround == [ready_at]


def test_delivered_aircraft_are_immediately_untasked() -> None:
    squadron = squadron_with_inventory(owned=4, untasked=1)
    squadron.pending_deliveries = 2
    squadron.location = Mock()
    squadron.location.unclaimed_parking.return_value = 10

    squadron.deliver_orders()

    assert squadron.owned_aircraft == 6
    assert squadron.untasked_aircraft == 3
    assert squadron.pending_deliveries == 0


def test_old_squadron_save_gets_empty_turnaround_state() -> None:
    squadron: Squadron = object.__new__(Squadron)

    squadron.__setstate__({"name": "Legacy Squadron"})

    assert squadron.aircraft_in_turnaround == []


def test_flight_delegates_delayed_aircraft_return() -> None:
    flight: Flight = object.__new__(Flight)
    flight.roster = Mock(max_size=2)
    flight.squadron = Mock()
    ready_at = NOW + timedelta(hours=1)

    flight.return_pilots_and_aircraft(ready_at)

    flight.roster.clear.assert_called_once_with()
    flight.squadron.return_aircraft.assert_called_once_with(2, ready_at)


@pytest.mark.parametrize(
    ("turnless", "turnaround_time", "expected_available_at"),
    [
        (True, timedelta(hours=1), NOW + timedelta(hours=1)),
        (True, timedelta(), None),
        (False, timedelta(hours=1), None),
    ],
)
def test_completed_flight_uses_turnaround_only_in_turnless_mode(
    turnless: bool,
    turnaround_time: timedelta,
    expected_available_at: datetime | None,
) -> None:
    settings = Mock(
        spec=Settings,
        turnless_mode=turnless,
        aircraft_turnaround_time=turnaround_time,
    )
    package = Mock()
    squadron = Mock(player=True)
    flight = Mock(
        package=package,
        squadron=squadron,
        state=Completed(Mock(), settings),
        cargo=None,
    )
    flight.should_halt_sim.return_value = False
    package.flights = [flight]

    blue = Mock()
    blue.ato.packages = [package]
    red = Mock()
    red.ato.packages = []
    game: Game = Mock(
        spec=Game,
        settings=settings,
        blue=blue,
        red=red,
        coalitions=[blue, red],
    )

    with patch("game.sim.aircraftsimulation.CombatInitiator.update_active_combats"):
        AircraftSimulation(game).on_game_tick(
            GameUpdateEvents(),
            NOW,
            timedelta(seconds=1),
            CombatResolutionMethod.SKIP,
            force_continue=False,
        )

    package.remove_flight.assert_called_once_with(
        flight, aircraft_available_at=expected_available_at
    )


def test_all_completed_flights_are_removed_from_mutating_package() -> None:
    settings = Mock(
        spec=Settings,
        turnless_mode=True,
        aircraft_turnaround_time=timedelta(hours=1),
    )
    package = Mock()
    squadron = Mock(player=True)
    flights = [
        Mock(
            package=package,
            squadron=squadron,
            state=Completed(Mock(), settings),
            cargo=None,
        )
        for _ in range(2)
    ]
    for flight in flights:
        flight.should_halt_sim.return_value = False
    package.flights = flights.copy()
    package.remove_flight.side_effect = (
        lambda flight, aircraft_available_at: package.flights.remove(flight)
    )

    blue = Mock()
    blue.ato.packages = [package]
    red = Mock()
    red.ato.packages = []
    game: Game = Mock(
        spec=Game,
        settings=settings,
        blue=blue,
        red=red,
        coalitions=[blue, red],
    )

    with patch("game.sim.aircraftsimulation.CombatInitiator.update_active_combats"):
        AircraftSimulation(game).on_game_tick(
            GameUpdateEvents(),
            NOW,
            timedelta(seconds=1),
            CombatResolutionMethod.SKIP,
            force_continue=False,
        )

    assert package.remove_flight.call_count == 2
    assert package.flights == []


def test_completed_airlift_delivers_surviving_cargo() -> None:
    settings = Mock(
        spec=Settings,
        turnless_mode=True,
        aircraft_turnaround_time=timedelta(),
    )
    cargo = Mock()
    cargo.transport = Mock()
    package = Mock()
    squadron = Mock(player=True)
    flight = Mock(
        package=package,
        squadron=squadron,
        state=Completed(Mock(), settings),
        cargo=cargo,
        flight_plan=Mock(spec=AirliftFlightPlan),
    )
    flight.should_halt_sim.return_value = False
    package.flights = [flight]
    blue = Mock()
    blue.ato.packages = [package]
    red = Mock()
    red.ato.packages = []
    game: Game = Mock(
        spec=Game,
        settings=settings,
        blue=blue,
        red=red,
        coalitions=[blue, red],
    )

    with patch("game.sim.aircraftsimulation.CombatInitiator.update_active_combats"):
        AircraftSimulation(game).on_game_tick(
            GameUpdateEvents(),
            NOW,
            timedelta(seconds=1),
            CombatResolutionMethod.SKIP,
            force_continue=False,
        )

    cargo.proceed.assert_called_once_with()


def test_aborted_airlift_does_not_deliver_cargo_on_landing() -> None:
    settings = Mock(
        spec=Settings,
        turnless_mode=True,
        aircraft_turnaround_time=timedelta(),
    )
    cargo = Mock()
    cargo.transport = Mock()
    package = Mock()
    squadron = Mock(player=True)
    flight = Mock(
        package=package,
        squadron=squadron,
        state=Completed(Mock(), settings),
        cargo=cargo,
        flight_plan=Mock(),
    )
    flight.should_halt_sim.return_value = False
    package.flights = [flight]
    blue = Mock()
    blue.ato.packages = [package]
    red = Mock()
    red.ato.packages = []
    game: Game = Mock(
        spec=Game,
        settings=settings,
        blue=blue,
        red=red,
        coalitions=[blue, red],
    )

    with patch("game.sim.aircraftsimulation.CombatInitiator.update_active_combats"):
        AircraftSimulation(game).on_game_tick(
            GameUpdateEvents(),
            NOW,
            timedelta(seconds=1),
            CombatResolutionMethod.SKIP,
            force_continue=False,
        )

    cargo.proceed.assert_not_called()
