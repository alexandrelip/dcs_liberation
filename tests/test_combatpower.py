from unittest.mock import Mock
from uuid import UUID

from game.ato import Flight, FlightType
from game.sim.combat.combatpower import (
    air_loss_probability,
    deterministic_roll,
    flight_combat_power,
    sam_loss_probability,
)
from game.utils import kph, nautical_miles


def flight(
    *,
    count: int = 2,
    price: int = 20,
    speed_kph: float = 1_500,
    task: FlightType = FlightType.INTERCEPTION,
    skill: str = "Good",
    missions: int = 0,
    health: float = 1,
    fuel_fraction: float = 1,
) -> Flight:
    pilot = Mock()
    pilot.record.missions_flown = missions
    aircraft = Mock(
        price=price,
        max_speed=kph(speed_kph),
    )
    aircraft.dcs_unit_type.fuel_max = 1_000
    squadron = Mock(player=True)
    squadron.settings.player_skill = skill
    squadron.settings.enemy_skill = skill
    member_roster = Mock()
    member_roster.iter_pilots.return_value = [pilot] * count
    return Mock(
        spec=Flight,
        count=count,
        unit_type=aircraft,
        flight_type=task,
        squadron=squadron,
        roster=member_roster,
        persisted_health_fraction=health,
        persisted_fuel=1_000 * fuel_fraction,
    )


def test_air_power_rewards_numbers_capability_skill_and_experience() -> None:
    baseline = flight_combat_power(flight())
    stronger = flight_combat_power(
        flight(
            count=4,
            price=80,
            speed_kph=2_000,
            skill="Excellent",
            missions=20,
        )
    )

    assert stronger > baseline * 4


def test_damage_and_low_fuel_reduce_air_power() -> None:
    healthy = flight_combat_power(flight())
    degraded = flight_combat_power(flight(health=0.5, fuel_fraction=0.25))

    assert degraded < healthy


def test_air_loss_probability_favors_stronger_side() -> None:
    assert air_loss_probability(100, 10) < air_loss_probability(10, 100)


def test_sam_probability_uses_threat_and_sead_reduces_risk() -> None:
    air_defense = Mock(value=100, alive_unit_count=4)
    air_defense.max_threat_range.return_value = nautical_miles(50)
    strike = flight(task=FlightType.STRIKE)
    sead = flight(task=FlightType.SEAD)

    assert sam_loss_probability(sead, [air_defense]) < sam_loss_probability(
        strike, [air_defense]
    )


def test_combat_roll_is_reproducible() -> None:
    combat_id = UUID("12345678-1234-5678-1234-567812345678")

    assert deterministic_roll(combat_id, 3) == deterministic_roll(combat_id, 3)
    assert deterministic_roll(combat_id, 3) != deterministic_roll(combat_id, 4)
