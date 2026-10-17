from pathlib import Path

from dcs.planes import plane_map

from game.ato import FlightType
from game.dcs.aircrafttype import AircraftType
from game.playableroster import BLUE_PLAYER_ROSTER
from game.settings import Settings
from pydcs_extensions import load_mods


def test_requested_blue_roster_has_exact_minimum_slots() -> None:
    requested = {entry.aircraft: entry.count for entry in BLUE_PLAYER_ROSTER}

    assert requested == {
        "F-16CM Fighting Falcon (Block 50)": 1,
        "F-5EM Tiger II": 1,
        "AMX A-1M": 1,
        "A-29B Super Tucano": 2,
        "F/A-18C Hornet (Lot 20)": 1,
        "A-4E Skyhawk": 1,
        "F-15C Eagle": 1,
        "JF-17 Thunder": 1,
        "AH-64D Apache Longbow": 1,
    }
    assert sum(requested.values()) == 10


def test_hornets_are_carrier_slots_and_apaches_are_cas() -> None:
    entries = {entry.aircraft: entry for entry in BLUE_PLAYER_ROSTER}

    assert entries["F/A-18C Hornet (Lot 20)"].carrier is True
    assert entries["A-4E Skyhawk"].carrier is True
    assert entries["AH-64D Apache Longbow"].task is FlightType.CAS


def test_brazilian_mod_aircraft_are_registered_and_flyable() -> None:
    load_mods()

    expected = {
        "F-5EM": "F-5EM Tiger II",
        "AMX_M": "AMX A-1M",
        "A-29B": "A-29B Super Tucano",
    }
    for dcs_id, variant in expected.items():
        assert dcs_id in plane_map
        aircraft = AircraftType.named(variant)
        assert aircraft.dcs_unit_type.id == dcs_id
        assert aircraft.flyable is True


def test_roster_and_mig29_doctrine_are_enabled_by_default() -> None:
    settings = Settings()

    assert settings.enable_expanded_blue_player_roster is True
    assert settings.perf_ensure_russian_mig29_defensive_flight is True
    assert settings.perf_mig29_retreat_to_sam is True
    assert settings.perf_mig29_outnumbered_radius == 120


def test_mig29_retreat_lua_uses_local_numbers_and_sam_route() -> None:
    script = Path("resources/plugins/base/dcs_liberation.lua").read_text(
        encoding="utf-8"
    )

    assert "if hostile > friendly then" in script
    assert "nearest_active_red_sam" in script
    assert "mist.goRoute(group, route)" in script
