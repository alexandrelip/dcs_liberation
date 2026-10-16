from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from game import Game
from game.ato import Flight
from game.ato.flightstate import InFlight
from game.debriefing import AircraftMissionState, StateData
from game.missiongenerator.aircraft.flightgroupconfigurator import (
    FlightGroupConfigurator,
)
from game.missiongenerator.aircraft.flightgroupspawner import FlightGroupSpawner
from game.sim.missionresultsprocessor import MissionResultsProcessor
from game.unitmap import FlyingUnit, UnitMap
from game.utils import kph

NOW = datetime(2000, 1, 1)


def aircraft_state(
    flying_unit: FlyingUnit,
    *,
    x: float = 10,
    y: float = 20,
    altitude: float = 3000,
    fuel_fraction: float = 0.5,
    health_fraction: float = 0.75,
    in_air: bool = True,
    ammo_remaining: int = 4,
) -> AircraftMissionState:
    return AircraftMissionState(
        unit=flying_unit,
        x=x,
        y=y,
        altitude=altitude,
        fuel_fraction=fuel_fraction,
        health_fraction=health_fraction,
        in_air=in_air,
        ammo_remaining=ammo_remaining,
    )


def test_state_data_accepts_old_exports_without_aircraft_states() -> None:
    data = {
        "mission_ended": True,
        "simulation_time_seconds": 60,
        "unit_lost_events": [],
        "kill_events": [],
        "crash_events": [],
        "dead_events": [],
        "killed_ground_units": [],
        "destroyed_objects_positions": [],
        "base_capture_events": [],
        "unit_hit_point_updates": [],
    }

    state = StateData.from_json(data, Mock(spec=UnitMap))

    assert state.aircraft_states == []


def test_aircraft_state_parser_clamps_simulator_values() -> None:
    unit_map = Mock(spec=UnitMap)
    flying_unit = Mock(spec=FlyingUnit)
    unit_map.flight.return_value = flying_unit

    state = AircraftMissionState.from_json(
        {
            "name": "Flight 1-1",
            "x": 1,
            "y": 2,
            "altitude": 3,
            "fuel_fraction": 1.5,
            "life": 150,
            "life_initial": 100,
            "in_air": True,
            "ammo_remaining": -1,
        },
        unit_map,
    )

    assert state is not None
    assert state.fuel_fraction == 1
    assert state.health_fraction == 1
    assert state.ammo_remaining == 0


def test_processor_persists_average_airborne_state() -> None:
    flight = Mock(spec=Flight)
    flight.unit_type.dcs_unit_type.fuel_max = 4000
    first = aircraft_state(
        Mock(spec=FlyingUnit, flight=flight),
        x=10,
        y=20,
        altitude=3000,
        fuel_fraction=0.5,
        health_fraction=0.8,
        ammo_remaining=4,
    )
    second = aircraft_state(
        Mock(spec=FlyingUnit, flight=flight),
        x=30,
        y=40,
        altitude=5000,
        fuel_fraction=0.25,
        health_fraction=0.6,
        ammo_remaining=2,
    )
    debriefing = Mock()
    debriefing.aircraft_mission_states.return_value = [first, second]
    game = Mock(spec=Game, simulation_time=NOW)
    expected_position = Mock()
    game.point_in_world.return_value = expected_position

    MissionResultsProcessor(game).commit_aircraft_mission_states(debriefing)

    assert flight.persisted_position is expected_position
    assert flight.persisted_altitude == 4000
    assert flight.persisted_fuel == 1500
    assert flight.persisted_health_fraction == 0.6
    assert flight.persisted_ammo_remaining == 6
    assert flight.persisted_state_time == NOW


def test_landed_aircraft_keeps_service_state_without_spawn_override() -> None:
    flight = Mock(spec=Flight)
    state = aircraft_state(
        Mock(spec=FlyingUnit, flight=flight),
        in_air=False,
        health_fraction=0.5,
        ammo_remaining=1,
    )
    debriefing = Mock()
    debriefing.aircraft_mission_states.return_value = [state]
    game = Mock(spec=Game, simulation_time=NOW)

    MissionResultsProcessor(game).commit_aircraft_mission_states(debriefing)

    assert flight.persisted_position is None
    assert flight.persisted_fuel is None
    assert flight.persisted_health_fraction == 0.5
    assert flight.persisted_ammo_remaining == 1


def test_damage_extends_aircraft_turnaround() -> None:
    flight: Flight = object.__new__(Flight)
    flight.persisted_health_fraction = 0.5

    duration = flight.turnaround_time(timedelta(hours=1))

    assert duration == timedelta(hours=2)


def test_future_simulation_invalidates_exact_spawn_snapshot() -> None:
    flight: Flight = object.__new__(Flight)
    setattr(flight, "persisted_position", Mock())
    flight.persisted_altitude = 3000
    flight.persisted_fuel = 1000
    flight.persisted_state_time = NOW
    flight.state = Mock()

    flight.on_game_tick(Mock(), NOW + timedelta(seconds=1), timedelta(seconds=1))

    assert getattr(flight, "persisted_position") is None
    assert getattr(flight, "persisted_altitude") is None
    assert getattr(flight, "persisted_fuel") is None
    assert getattr(flight, "persisted_state_time") is None


def test_mid_mission_spawn_uses_persisted_position_and_altitude() -> None:
    persisted_position = Mock()
    state = Mock(spec=InFlight)
    state.estimate_speed.return_value = kph(500)
    flight = Mock(
        spec=Flight,
        state=state,
        persisted_position=persisted_position,
        persisted_altitude=3500,
        count=2,
    )
    flight.unit_type.dcs_unit_type = Mock()
    spawner: FlightGroupSpawner = object.__new__(FlightGroupSpawner)
    spawner.flight = flight
    spawner.country = Mock()
    spawner.mission = Mock()
    spawner.mission.flight_group.return_value.points = [Mock()]

    with patch(
        "game.missiongenerator.aircraft.flightgroupspawner.namegen.next_aircraft_name",
        return_value="Flight",
    ):
        spawner.generate_mid_mission()

    call = spawner.mission.flight_group.call_args
    assert call.kwargs["position"] is not persisted_position
    assert call.kwargs["altitude"] == 3500
    state.estimate_position.assert_not_called()
    state.estimate_altitude.assert_not_called()


def test_payload_configuration_uses_persisted_fuel_for_ai() -> None:
    unit = Mock()
    flight = Mock(
        spec=Flight,
        persisted_fuel=1234,
        roster=Mock(),
        state=Mock(),
    )
    flight.roster.iter_pilots.return_value = [None]
    configurator: FlightGroupConfigurator = object.__new__(FlightGroupConfigurator)
    configurator.flight = flight
    configurator.group = Mock(units=[unit])

    configurator.setup_fuel()

    assert unit.fuel == 1234
    flight.state.estimate_fuel.assert_not_called()
