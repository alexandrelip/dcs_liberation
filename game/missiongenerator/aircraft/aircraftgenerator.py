from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from typing import Any, Dict, TYPE_CHECKING

from dcs.country import Country
from dcs.mission import Mission
from dcs.terrain.terrain import NoParkingSlotError
from dcs.unitgroup import FlyingGroup, StaticGroup

from game.ato.airtaaskingorder import AirTaskingOrder
from game.ato.flight import Flight
from game.ato.flightstate import Completed
from game.ato.flighttype import FlightType
from game.ato.package import Package
from game.ato.starttype import StartType
from game.factions.faction import Faction
from game.missiongenerator.missiondata import MissionData
from game.playableroster import RUSSIAN_MIG29_FLIGHT_NAME
from game.radio.radios import RadioRegistry
from game.radio.tacan import TacanRegistry
from game.runways import RunwayData
from game.settings import Settings
from game.theater.controlpoint import (
    Airfield,
    ControlPoint,
    Fob,
)
from game.unitmap import UnitMap
from .aircraftpainter import AircraftPainter
from .flightdata import FlightData
from .flightgroupconfigurator import FlightGroupConfigurator
from .flightgroupspawner import FlightGroupSpawner

if TYPE_CHECKING:
    from game import Game
    from game.squadrons import Squadron


@dataclass
class AirUnitBudget:
    combat_aircraft: int
    helicopters: int
    tankers: int
    awacs: int
    total_units: int

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        preallocated_combat_aircraft: int = 0,
        total_units_available: int | None = None,
    ) -> AirUnitBudget:
        return cls(
            combat_aircraft=max(
                0,
                settings.perf_max_active_combat_aircraft_per_coalition
                - preallocated_combat_aircraft,
            ),
            helicopters=settings.perf_max_active_helicopters_per_coalition,
            tankers=settings.perf_max_active_tankers_per_coalition,
            awacs=settings.perf_max_active_awacs_per_coalition,
            total_units=(
                settings.perf_max_active_units_per_coalition
                if total_units_available is None
                else total_units_available
            ),
        )

    def claim(self, flight: Flight, required_for_player: bool) -> bool:
        if flight.is_helo:
            category = "helicopters"
        elif flight.flight_type is FlightType.REFUELING:
            category = "tankers"
        elif flight.flight_type is FlightType.AEWC:
            category = "awacs"
        else:
            category = "combat_aircraft"

        available = getattr(self, category)
        if not required_for_player and (
            flight.count > available or flight.count > self.total_units
        ):
            return False
        setattr(self, category, max(0, available - flight.count))
        self.total_units = max(0, self.total_units - flight.count)
        return True


class AircraftGenerator:
    def __init__(
        self,
        mission: Mission,
        settings: Settings,
        game: Game,
        time: datetime,
        radio_registry: RadioRegistry,
        tacan_registry: TacanRegistry,
        unit_map: UnitMap,
        mission_data: MissionData,
        helipads: dict[ControlPoint, StaticGroup],
    ) -> None:
        self.mission = mission
        self.settings = settings
        self.game = game
        self.time = time
        self.radio_registry = radio_registry
        self.tacan_registy = tacan_registry
        self.unit_map = unit_map
        # A list of per-package briefing data, which is in turn a list of per-flight
        # briefing data.
        self.briefing_data: list[list[FlightData]] = []
        self.mission_data = mission_data
        self.helipads = helipads

    @cached_property
    def use_client(self) -> bool:
        """True if Client should be used instead of Player."""
        blue_clients = self.client_slots_in_ato(self.game.blue.ato)
        red_clients = self.client_slots_in_ato(self.game.red.ato)
        return blue_clients + red_clients > 1

    @staticmethod
    def client_slots_in_ato(ato: AirTaskingOrder) -> int:
        total = 0
        for package in ato.packages:
            for flight in package.flights:
                total += flight.client_count
        return total

    def clear_parking_slots(self) -> None:
        for cp in self.game.theater.controlpoints:
            for parking_slot in cp.parking_slots:
                parking_slot.unit_id = None

    def generate_flights(
        self,
        country: Country,
        ato: AirTaskingOrder,
        dynamic_runways: Dict[str, RunwayData],
        player: bool,
    ) -> None:
        """Adds aircraft to the mission for every flight in the ATO.

        Aircraft generation is done by walking the ATO and spawning each flight in turn.
        After the flight is generated the group is added to the UnitMap so aircraft
        deaths can be tracked.

        Args:
            country: The country from the mission to use for this ATO.
            ato: The ATO to spawn aircraft for.
            dynamic_runways: Runway data for carriers and FARPs.
        """
        preallocated_combat_aircraft = sum(
            1 for jtac in self.mission_data.jtacs if jtac.blue == player
        )
        coalition_name = "blue" if player else "red"
        total_units_available = max(
            0,
            self.settings.perf_max_active_units_per_coalition
            - self.mission_data.selected_tactical_units[coalition_name],
        )
        budget = AirUnitBudget.from_settings(
            self.settings,
            preallocated_combat_aircraft,
            total_units_available,
        )
        packages = sorted(
            ato.packages,
            key=lambda package: (
                not package.has_players,
                not any(
                    flight.custom_name == RUSSIAN_MIG29_FLIGHT_NAME
                    for flight in package.flights
                ),
            ),
        )
        for package in packages:
            if not package.flights:
                continue
            if package.has_players:
                anchor = (package.target.position.x, package.target.position.y)
                if anchor not in self.mission_data.activation_anchor_points:
                    self.mission_data.activation_anchor_points.append(anchor)
            package_briefing_data: list[FlightData] = []
            for flight in package.flights:
                if not flight.alive:
                    continue
                if (
                    flight.departure.is_fleet
                    and flight.departure.name not in dynamic_runways
                ):
                    logging.info(
                        "Keeping %s flight from omitted fleet base %s abstract",
                        flight.flight_type,
                        flight.departure,
                    )
                    continue
                if not budget.claim(flight, package.has_players):
                    logging.info(
                        "Keeping %s %s flight abstract to respect the active-aircraft "
                        "budget",
                        flight.count,
                        flight.flight_type,
                    )
                    continue
                logging.info(f"Generating flight: {flight.unit_type}")
                group, briefing_data = self.create_and_configure_flight(
                    flight, country, dynamic_runways
                )
                if package.has_players:
                    self.mission_data.activation_anchor_groups.append(group.name)
                package_briefing_data.append(briefing_data)
                self.unit_map.add_aircraft(group, flight)
                self.mission_data.selected_tactical_units[
                    coalition_name
                ] += flight.count
            self.briefing_data.append(package_briefing_data)

    def spawn_unused_aircraft(
        self, player_country: Country, enemy_country: Country
    ) -> None:
        for control_point in self.game.theater.controlpoints:
            if not isinstance(control_point, Airfield):
                continue

            faction = self.game.coalition_for(control_point.captured).faction
            if control_point.captured:
                country = player_country
            else:
                country = enemy_country

            for squadron in control_point.squadrons:
                try:
                    self._spawn_unused_for(squadron, country, faction)
                except NoParkingSlotError:
                    # If we run out of parking, stop spawning aircraft at this base.
                    break

    def _spawn_unused_for(
        self, squadron: Squadron, country: Country, faction: Faction
    ) -> None:
        assert isinstance(squadron.location, Airfield)
        for _ in range(squadron.untasked_aircraft):
            # Creating a flight even those this isn't a fragged mission lets us
            # reuse the existing debriefing code.
            # TODO: Special flight type?
            flight = Flight(
                Package(squadron.location, self.game.db.flights),
                faction.country,
                squadron,
                1,
                FlightType.IDLE,
                StartType.COLD,
                divert=None,
            )
            flight.state = Completed(flight, self.game.settings)

            group = FlightGroupSpawner(
                flight, country, self.mission, self.helipads
            ).create_idle_aircraft()
            AircraftPainter(flight, group).apply_livery()
            self.unit_map.add_aircraft(group, flight)

    def create_and_configure_flight(
        self, flight: Flight, country: Country, dynamic_runways: Dict[str, RunwayData]
    ) -> tuple[FlyingGroup[Any], FlightData]:
        """Creates and configures the flight group in the mission."""
        group = FlightGroupSpawner(
            flight, country, self.mission, self.helipads
        ).create_flight_group()

        briefing_data = FlightGroupConfigurator(
            flight,
            group,
            self.game,
            self.mission,
            self.time,
            self.radio_registry,
            self.tacan_registy,
            self.mission_data,
            dynamic_runways,
            self.use_client,
            self.unit_map,
        ).configure()

        wpt = group.waypoint("LANDING")
        if flight.is_helo and isinstance(flight.arrival, Fob) and wpt:
            hpad = self.helipads[flight.arrival].units.pop(0)
            wpt.helipad_id = hpad.id
            wpt.link_unit = hpad.id
            self.helipads[flight.arrival].units.append(hpad)

        return group, briefing_data
