from __future__ import annotations

import math
import random
from collections.abc import Iterable
from uuid import UUID

from game.ato import Flight, FlightType
from game.theater import TheaterGroundObject

SKILL_FACTORS = {
    "Average": 0.85,
    "Good": 1.0,
    "High": 1.15,
    "Excellent": 1.3,
}


def flight_combat_power(flight: Flight) -> float:
    aircraft = flight.unit_type
    price_factor = math.sqrt(max(1.0, float(aircraft.price)))
    speed_factor = max(0.6, min(1.6, aircraft.max_speed.kph / 1_500))
    role_factor = 1.2 if flight.flight_type.is_air_to_air else 0.75
    skill_name = (
        flight.squadron.settings.player_skill
        if flight.squadron.player
        else flight.squadron.settings.enemy_skill
    )
    skill_factor = SKILL_FACTORS.get(skill_name, 1.0)
    pilots = [pilot for pilot in flight.roster.iter_pilots() if pilot is not None]
    experience = (
        sum(pilot.record.missions_flown for pilot in pilots) / len(pilots)
        if pilots
        else 0.0
    )
    experience_factor = 1.0 + min(0.2, experience * 0.01)
    health_factor = 0.5 + 0.5 * max(0.0, min(1.0, flight.persisted_health_fraction))
    max_fuel = float(aircraft.dcs_unit_type.fuel_max)
    if flight.persisted_fuel is None or max_fuel <= 0:
        fuel_factor = 1.0
    else:
        fuel_fraction = max(0.0, min(1.0, flight.persisted_fuel / max_fuel))
        fuel_factor = 0.6 + 0.4 * fuel_fraction
    return (
        flight.count
        * price_factor
        * speed_factor
        * role_factor
        * skill_factor
        * experience_factor
        * health_factor
        * fuel_factor
    )


def side_combat_power(flights: Iterable[Flight]) -> float:
    return sum(flight_combat_power(flight) for flight in flights)


def air_loss_probability(own_power: float, opponent_power: float) -> float:
    total = own_power + opponent_power
    if total <= 0:
        return 0.5
    opponent_share = opponent_power / total
    return max(0.05, min(0.9, 0.1 + 0.65 * opponent_share))


def sam_threat_power(air_defenses: Iterable[TheaterGroundObject]) -> float:
    power = 0.0
    for air_defense in air_defenses:
        value_factor = math.sqrt(max(1.0, float(air_defense.value)))
        range_factor = 1.0 + air_defense.max_threat_range().nautical_miles / 100
        count_factor = math.sqrt(max(1, air_defense.alive_unit_count))
        power += value_factor * range_factor * count_factor
    return power


def sam_loss_probability(
    flight: Flight,
    air_defenses: Iterable[TheaterGroundObject],
) -> float:
    threat = sam_threat_power(air_defenses)
    aircraft = flight_combat_power(flight)
    if threat <= 0:
        return 0.0
    probability = threat / (threat + aircraft)
    if flight.flight_type in {FlightType.SEAD, FlightType.DEAD}:
        probability *= 0.6
    return max(0.02, min(0.95, probability))


def deterministic_roll(combat_id: UUID, discriminator: int = 0) -> float:
    return random.Random(combat_id.int ^ discriminator).random()
