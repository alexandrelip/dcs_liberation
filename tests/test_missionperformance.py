from pathlib import Path
from unittest.mock import Mock, patch

from game import Game
from game.ato import FlightType
from game.ato.starttype import StartType
from game.data.units import UnitClass
from game.ground_forces.ai_ground_planner import CombatGroup, CombatGroupRole
from game.missiongenerator.aircraft.aircraftgenerator import AirUnitBudget
from game.missiongenerator.aircraft.waypoints.waypointgenerator import (
    WaypointGenerator,
)
from game.missiongenerator.missiondata import MissionData
from game.missiongenerator.missiongenerator import MissionGenerator
from game.missiongenerator.tgogenerator import GroundObjectGenerator
from game.settings import Settings
from game.utils import meters


def mission_generator_with_settings(settings: Settings) -> MissionGenerator:
    generator = MissionGenerator.__new__(MissionGenerator)
    generator.mission = Mock()
    generator.game = Mock(settings=settings)
    generator.game.blue.country_name = "Blue"
    generator.game.red.country_name = "Red"
    generator.time = Mock()
    generator.radio_registry = Mock()
    generator.tacan_registry = Mock()
    generator.unit_map = Mock()
    generator.mission_data = Mock()
    return generator


def test_performance_defaults_reduce_active_mission_entities() -> None:
    settings = Settings()

    assert settings.perf_culling is True
    assert settings.perf_spawn_unused_aircraft is False
    assert settings.perf_late_activate_ai_aircraft is True
    assert settings.perf_dynamic_ground_activation is True
    assert settings.perf_dynamic_ground_activation_distance == 35
    assert settings.perf_script_update_hz == 15
    assert settings.perf_ground_ai_active_percent == 15
    assert settings.perf_max_active_sam_sites_per_coalition == 3
    assert settings.perf_max_active_helicopters_per_coalition == 6
    assert settings.perf_max_active_frontline_vehicles_per_coalition == 15
    assert settings.perf_max_active_infantry_per_coalition == 5
    assert settings.perf_max_active_combat_aircraft_per_coalition == 20
    assert settings.perf_max_active_tankers_per_coalition == 1
    assert settings.perf_max_active_awacs_per_coalition == 1
    assert settings.perf_max_active_carriers_per_coalition == 1
    assert settings.perf_max_active_ships_per_coalition == 6
    assert settings.continuous_ground_force_offensive is True


def test_untasked_aircraft_are_only_spawned_when_enabled() -> None:
    settings = Settings()
    generator = mission_generator_with_settings(settings)
    tgo_generator = Mock(runways={})

    with patch(
        "game.missiongenerator.missiongenerator.AircraftGenerator"
    ) as aircraft_generator_type:
        aircraft_generator = aircraft_generator_type.return_value
        aircraft_generator.briefing_data = []

        generator.generate_air_units(tgo_generator)
        aircraft_generator.spawn_unused_aircraft.assert_not_called()

        settings.perf_spawn_unused_aircraft = True
        generator.generate_air_units(tgo_generator)
        aircraft_generator.spawn_unused_aircraft.assert_called_once()


def test_land_based_ai_cold_starts_use_late_activation_by_default() -> None:
    generator = WaypointGenerator.__new__(WaypointGenerator)
    generator.settings = Settings()
    generator.flight = Mock(
        client_count=0,
        start_type=StartType.COLD,
        departure=Mock(is_fleet=False),
    )

    assert generator.should_activate_late() is True

    generator.settings.perf_late_activate_ai_aircraft = False

    assert generator.should_activate_late() is False


def test_ground_object_groups_are_deferred_outside_the_dcs_bubble() -> None:
    settings = Settings()
    game = Mock(settings=settings)
    ground_object = Mock()
    ground_object.max_threat_range.return_value = meters(100_000)
    ground_object.is_friendly.return_value = True
    ground_object.id = "site-id"
    mission_data = MissionData()
    generator = GroundObjectGenerator(
        ground_object,
        Mock(),
        game,
        Mock(),
        Mock(),
        mission_data,
    )
    group = Mock()
    group.name = "SAM group"
    group.units = [Mock(position=Mock(x=10, y=20))]
    group.late_activation = False
    theater_unit = Mock()
    theater_unit.unit_type.unit_class = UnitClass.TANK
    theater_unit.is_vehicle = True

    generator.defer_group(group, [theater_unit], "ground")

    assert group.late_activation is True
    assert len(mission_data.deferred_ground_groups) == 1
    deferred = mission_data.deferred_ground_groups[0]
    assert deferred.group_name == "SAM group"
    assert deferred.position_x == 10
    assert deferred.position_y == 20
    assert deferred.activation_distance == 118_520
    assert deferred.coalition == "blue"
    assert deferred.kind == "ground"
    assert deferred.site_name == "site-id"
    assert deferred.unit_count == 1


def test_deferred_force_candidates_are_trimmed_to_requested_limits() -> None:
    settings = Settings()
    game = Mock(settings=settings)
    ground_object = Mock()
    ground_object.is_friendly.return_value = True
    ground_object.id = "site-id"
    mission_data = MissionData()
    generator = GroundObjectGenerator(
        ground_object,
        Mock(),
        game,
        Mock(),
        Mock(),
        mission_data,
    )

    assert len(generator.claim_deferred_units("ground", [Mock()] * 20)) == 15
    assert generator.claim_deferred_units("ground", [Mock()]) == []
    assert len(generator.claim_deferred_units("infantry", [Mock()] * 10)) == 5
    assert len(generator.claim_deferred_units("ship", [Mock()] * 10)) == 6
    sam_claims = []
    for site_number in range(4):
        ground_object.id = f"sam-{site_number}"
        sam_claims.append(generator.claim_deferred_units("sam", [Mock()]))
    assert [len(claim) for claim in sam_claims] == [1, 1, 1, 0]


def test_air_budget_enforces_requested_per_coalition_limits() -> None:
    budget = AirUnitBudget.from_settings(Settings())
    combat = Mock(is_helo=False, flight_type=FlightType.STRIKE, count=4)
    helicopter = Mock(is_helo=True, flight_type=FlightType.CAS, count=2)
    tanker = Mock(is_helo=False, flight_type=FlightType.REFUELING, count=1)
    awacs = Mock(is_helo=False, flight_type=FlightType.AEWC, count=1)

    assert [budget.claim(combat, False) for _ in range(6)] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert [budget.claim(helicopter, False) for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    assert budget.claim(tanker, False) is True
    assert budget.claim(tanker, False) is False
    assert budget.claim(awacs, False) is True
    assert budget.claim(awacs, False) is False
    assert budget.claim(combat, True) is True


def test_preallocated_jtac_uses_combat_aircraft_budget() -> None:
    budget = AirUnitBudget.from_settings(
        Settings(),
        preallocated_combat_aircraft=1,
    )

    assert budget.combat_aircraft == 19


def test_frontline_vehicle_budget_clips_last_group_to_fifteen_units() -> None:
    unit_type = Mock()
    groups = [
        CombatGroup(CombatGroupRole.TANK, unit_type, 8),
        CombatGroup(CombatGroupRole.IFV, unit_type, 8),
        CombatGroup(CombatGroupRole.ARTILLERY, unit_type, 4),
    ]
    budget = {True: 15, False: 15}

    selected = MissionGenerator._limit_frontline_groups(groups, budget, player=True)

    assert [group.role for group in selected] == [
        CombatGroupRole.TANK,
        CombatGroupRole.IFV,
    ]
    assert [group.size for group in selected] == [8, 7]
    assert budget[True] == 0
    assert budget[False] == 15


def test_only_player_packages_expand_the_detailed_culling_bubble() -> None:
    game = Game.__new__(Game)
    front_position = Mock(name="front-position")
    blue_position = Mock(name="blue-position")
    red_position = Mock(name="red-position")
    player_target = Mock(name="player-target")
    ai_target = Mock(name="ai-target")
    front_line = Mock()
    front_line.blue_cp.position = blue_position
    front_line.red_cp.position = red_position
    game.theater = Mock()
    game.theater.conflicts.return_value = [front_line]
    game.theater.controlpoints = []
    player_package = Mock(
        has_players=True,
        primary_task=FlightType.STRIKE,
        target=Mock(position=player_target),
    )
    ai_package = Mock(
        has_players=False,
        primary_task=FlightType.STRIKE,
        target=Mock(position=ai_target),
    )
    game.blue = Mock(ato=Mock(packages=[player_package]))
    game.red = Mock(ato=Mock(packages=[ai_package]))
    events = Mock()

    with patch(
        "game.missiongenerator.frontlineconflictdescription."
        "FrontLineConflictDescription.frontline_position",
        return_value=(front_position, Mock()),
    ):
        game.compute_unculled_zones(events)

    assert game.get_culling_zones() == [
        front_position,
        blue_position,
        red_position,
        player_target,
    ]


def test_lua_ai_cohort_never_rounds_above_configured_percentage() -> None:
    script = Path("resources/plugins/base/dcs_liberation.lua").read_text(
        encoding="utf-8"
    )

    assert "local exact_active_count = group_count * active_percent / 100" in script
    assert "local active_count = math.floor(exact_active_count)" in script
