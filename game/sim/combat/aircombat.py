from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from shapely.ops import unary_union

from game.ato.flightstate import InCombat, InFlight
from game.settings.settings import CombatResolutionMethod
from game.utils import dcs_to_shapely_point
from .combatpower import (
    air_loss_probability,
    deterministic_roll,
    flight_combat_power,
    side_combat_power,
)
from .joinablecombat import JoinableCombat
from .. import GameUpdateEvents

if TYPE_CHECKING:
    from game.ato import Flight
    from ..simulationresults import SimulationResults


class AirCombat(JoinableCombat):
    def __init__(self, freeze_duration: timedelta, flights: list[Flight]) -> None:
        super().__init__(freeze_duration, flights)
        footprints = []
        for flight in self.flights:
            if (region := flight.state.a2a_commit_region()) is not None:
                footprints.append(region)
        self.footprint = unary_union(footprints)

    def joinable_by(self, flight: Flight) -> bool:
        if not flight.state.will_join_air_combat:
            return False

        if not isinstance(flight.state, InFlight):
            raise NotImplementedError(
                f"Only InFlight flights are expected to join air combat. {flight} is "
                "not InFlight"
            )

        if self.footprint.intersects(
            dcs_to_shapely_point(flight.state.estimate_position())
        ):
            return True
        return False

    def __str__(self) -> str:
        blue_flights = []
        red_flights = []
        for flight in self.flights:
            if flight.squadron.player:
                blue_flights.append(str(flight))
            else:
                red_flights.append(str(flight))

        blue = ", ".join(blue_flights)
        red = ", ".join(red_flights)
        return f"air combat {blue} vs {red}"

    def because(self) -> str:
        return f"of {self}"

    def describe(self) -> str:
        return "in air-to-air combat"

    def resolve(
        self,
        results: SimulationResults,
        events: GameUpdateEvents,
        time: datetime,
        elapsed_time: timedelta,
        resolution_method: CombatResolutionMethod,
    ) -> None:

        if resolution_method is CombatResolutionMethod.SKIP:
            for flight in self.flights:
                assert isinstance(flight.state, InCombat)
                flight.state.exit_combat(events, time, elapsed_time)
            return

        blue = []
        red = []
        for flight in self.flights:
            if flight.squadron.player:
                blue.append(flight)
            else:
                red.append(flight)
        blue_power = side_combat_power(blue)
        red_power = side_combat_power(red)
        logging.debug(
            "%s auto-resolve power: blue=%.2f red=%.2f",
            self,
            blue_power,
            red_power,
        )
        losses = []
        for index, flight in enumerate(
            sorted(self.flights, key=lambda candidate: candidate.id.int)
        ):
            assert isinstance(flight.state, InCombat)
            if flight.squadron.player:
                own_power = flight_combat_power(flight)
                opponent_power = red_power
            else:
                own_power = flight_combat_power(flight)
                opponent_power = blue_power
            probability = air_loss_probability(own_power, opponent_power)
            if deterministic_roll(self.id, index + 1) < probability:
                flight.kill(results, events)
                losses.append(str(flight))
            else:
                flight.state.exit_combat(events, time, elapsed_time)
        results.record_combat(
            "Air combat auto-resolved",
            (
                f"{self}; blue power={blue_power:.2f}; red power={red_power:.2f}; "
                f"lost flights={', '.join(losses) if losses else 'none'}"
            ),
        )
