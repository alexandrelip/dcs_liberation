from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from game import persistence
from game.ato import Flight, FlightType, Package
from game.ato.starttype import StartType
from game.dcs.aircrafttype import AircraftType
from game.squadrons import Pilot, Squadron
from game.squadrons.operatingbases import OperatingBases
from game.theater import ControlPoint, FrontLine, OffMapSpawn

if TYPE_CHECKING:
    from game import Game


PLAYER_ROSTER_PREFIX = "Expanded player roster"


@dataclass(frozen=True)
class PlayerRosterEntry:
    aircraft: str
    count: int
    task: FlightType
    carrier: bool = False
    required_mod_directory: str | None = None

    @property
    def flight_name(self) -> str:
        return f"{PLAYER_ROSTER_PREFIX}: {self.aircraft}"


BLUE_PLAYER_ROSTER = (
    PlayerRosterEntry("F-16CM Fighting Falcon (Block 50)", 1, FlightType.BARCAP),
    PlayerRosterEntry(
        "F-5EM Tiger II",
        1,
        FlightType.BARCAP,
        required_mod_directory="F5EM_beta",
    ),
    PlayerRosterEntry(
        "AMX A-1M",
        1,
        FlightType.CAS,
        required_mod_directory="AMX",
    ),
    PlayerRosterEntry(
        "A-29B Super Tucano",
        2,
        FlightType.CAS,
        required_mod_directory="A29MEFM",
    ),
    PlayerRosterEntry(
        "F/A-18C Hornet (Lot 20)",
        1,
        FlightType.BARCAP,
        carrier=True,
    ),
    PlayerRosterEntry(
        "A-4E Skyhawk",
        1,
        FlightType.CAS,
        carrier=True,
        required_mod_directory="A-4E-C",
    ),
    PlayerRosterEntry("F-15C Eagle", 1, FlightType.BARCAP),
    PlayerRosterEntry("JF-17 Thunder", 1, FlightType.BARCAP),
    PlayerRosterEntry("AH-64D Apache Longbow", 1, FlightType.CAS),
)


class BluePlayableRoster:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.coalition = game.blue

    def ensure(self, now: datetime) -> None:
        if not self.game.settings.enable_expanded_blue_player_roster:
            return

        for entry in BLUE_PLAYER_ROSTER:
            if not self._mod_is_installed(entry):
                logging.warning(
                    "Skipping %s because DCS mod directory %s is not installed",
                    entry.aircraft,
                    entry.required_mod_directory,
                )
                continue
            try:
                aircraft = AircraftType.named(entry.aircraft)
            except KeyError:
                logging.exception("Unknown expanded-roster aircraft %s", entry.aircraft)
                continue

            existing = self._existing_flight_count(entry)
            if existing >= entry.count:
                continue

            base = self._select_base(aircraft, entry.carrier)
            if base is None:
                logging.error(
                    "No compatible blue %s found for %s",
                    "carrier" if entry.carrier else "base",
                    entry.aircraft,
                )
                continue

            squadron = self._get_or_create_squadron(entry, aircraft, base)
            if squadron.location != base:
                squadron.assign_to_base(base)
            count = min(entry.count - existing, squadron.untasked_aircraft)
            if count <= 0:
                logging.warning("No available aircraft for %s", entry.flight_name)
                continue
            self._create_flight(entry, squadron, base, count, now)

    @staticmethod
    def _mod_is_installed(entry: PlayerRosterEntry) -> bool:
        if entry.required_mod_directory is None:
            return True
        try:
            saved_games = Path(persistence.base_path())
        except AssertionError:
            return False
        return (
            saved_games / "Mods" / "aircraft" / entry.required_mod_directory
        ).is_dir()

    def _existing_flight_count(self, entry: PlayerRosterEntry) -> int:
        return sum(
            flight.count
            for package in self.coalition.ato.packages
            for flight in package.flights
            if flight.custom_name == entry.flight_name
        )

    def _select_base(
        self, aircraft: AircraftType, carrier_required: bool
    ) -> ControlPoint | None:
        candidates = [
            control_point
            for control_point in self.game.theater.player_points()
            if control_point.runway_is_operational()
            and not isinstance(control_point, OffMapSpawn)
            and control_point.can_operate(aircraft)
            and (
                control_point.is_carrier
                if carrier_required
                else not control_point.is_fleet
            )
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda control_point: (
                control_point.unclaimed_parking(),
                -self._distance_to_front(control_point),
                control_point.name,
            ),
        )

    def _distance_to_front(self, control_point: ControlPoint) -> float:
        return min(
            (
                control_point.position.distance_to_point(front_line.position)
                for front_line in self.game.theater.conflicts()
            ),
            default=0,
        )

    def _get_or_create_squadron(
        self,
        entry: PlayerRosterEntry,
        aircraft: AircraftType,
        base: ControlPoint,
    ) -> Squadron:
        squadron_name = entry.flight_name
        for squadron in self.coalition.air_wing.iter_squadrons():
            if squadron.name == squadron_name:
                return squadron

        pilots = [
            Pilot(f"{aircraft.display_name} Player {index + 1}", player=True)
            for index in range(entry.count)
        ]
        squadron = Squadron(
            name=squadron_name,
            nickname=None,
            country=self.coalition.country_name,
            role="Player Squadron",
            aircraft=aircraft,
            max_size=entry.count,
            livery=None,
            primary_task=entry.task,
            auto_assignable_mission_types=set(),
            operating_bases=OperatingBases.default_for_aircraft(aircraft),
            female_pilot_percentage=0,
            pilot_pool=[],
            coalition=self.coalition,
            flight_db=self.game.db.flights,
            settings=self.game.settings,
            location=base,
        )
        squadron.current_roster = pilots
        squadron.available_pilots = list(pilots)
        squadron.owned_aircraft = entry.count
        squadron.untasked_aircraft = entry.count
        self.coalition.air_wing.add_squadron(squadron)
        return squadron

    def _create_flight(
        self,
        entry: PlayerRosterEntry,
        squadron: Squadron,
        base: ControlPoint,
        count: int,
        now: datetime,
    ) -> None:
        target = self._target_for(entry.task, base)
        if target is None:
            logging.error("No valid target for %s", entry.flight_name)
            return

        package = Package(target, self.game.db.flights, auto_asap=True)
        flight = Flight(
            package=package,
            country=self.coalition.country_name,
            squadron=squadron,
            count=count,
            flight_type=entry.task,
            start_type=StartType.COLD,
            divert=None,
            custom_name=entry.flight_name,
        )
        flight.callsign = self.coalition.callsign_generator.alloc_callsign(flight)
        package.add_flight(flight)
        try:
            flight.recreate_flight_plan()
            package.set_tot_asap(now)
        except Exception:
            package.remove_flight(flight)
            raise
        self.coalition.ato.add_package(package)

    def _target_for(
        self, task: FlightType, base: ControlPoint
    ) -> ControlPoint | FrontLine | None:
        if task is FlightType.BARCAP:
            return base
        front_lines = list(self.game.theater.conflicts())
        if not front_lines:
            return None
        return min(
            front_lines,
            key=lambda front_line: base.position.distance_to_point(front_line.position),
        )


RUSSIAN_MIG29_FLIGHT_NAME = "Russian defensive MiG-29"


class RussianDefensiveRoster:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.coalition = game.red

    def ensure(self, now: datetime) -> None:
        if not self.game.settings.perf_ensure_russian_mig29_defensive_flight:
            return
        if self.coalition.country_name != "Russia":
            return
        if any(
            flight.custom_name == RUSSIAN_MIG29_FLIGHT_NAME
            for package in self.coalition.ato.packages
            for flight in package.flights
        ):
            return

        aircraft = AircraftType.named("MiG-29S Fulcrum-C")
        base = self._select_base(aircraft)
        if base is None:
            logging.error("No compatible Russian base found for defensive MiG-29S")
            return
        squadron = self._get_or_create_squadron(aircraft, base)
        count = min(2, squadron.untasked_aircraft)
        if count <= 0:
            return

        package = Package(base, self.game.db.flights, auto_asap=True)
        flight = Flight(
            package=package,
            country=self.coalition.country_name,
            squadron=squadron,
            count=count,
            flight_type=FlightType.BARCAP,
            start_type=self.game.settings.default_start_type,
            divert=None,
            custom_name=RUSSIAN_MIG29_FLIGHT_NAME,
        )
        flight.callsign = self.coalition.callsign_generator.alloc_callsign(flight)
        package.add_flight(flight)
        try:
            flight.recreate_flight_plan()
            package.set_tot_asap(now)
        except Exception:
            package.remove_flight(flight)
            raise
        self.coalition.ato.add_package(package)

    def _select_base(self, aircraft: AircraftType) -> ControlPoint | None:
        candidates = [
            control_point
            for control_point in self.game.theater.enemy_points()
            if control_point.runway_is_operational()
            and not control_point.is_fleet
            and not isinstance(control_point, OffMapSpawn)
            and control_point.can_operate(aircraft)
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda control_point: (
                self._distance_to_front(control_point),
                -control_point.unclaimed_parking(),
                control_point.name,
            ),
        )

    def _distance_to_front(self, control_point: ControlPoint) -> float:
        return min(
            (
                control_point.position.distance_to_point(front_line.position)
                for front_line in self.game.theater.conflicts()
            ),
            default=0,
        )

    def _get_or_create_squadron(
        self, aircraft: AircraftType, base: ControlPoint
    ) -> Squadron:
        for squadron in self.coalition.air_wing.iter_squadrons():
            if squadron.name == RUSSIAN_MIG29_FLIGHT_NAME:
                if squadron.location != base:
                    squadron.assign_to_base(base)
                return squadron

        pilots = [Pilot("MiG-29 Defender 1"), Pilot("MiG-29 Defender 2")]
        squadron = Squadron(
            name=RUSSIAN_MIG29_FLIGHT_NAME,
            nickname=None,
            country=self.coalition.country_name,
            role="Air Defense Squadron",
            aircraft=aircraft,
            max_size=2,
            livery=None,
            primary_task=FlightType.BARCAP,
            auto_assignable_mission_types=set(),
            operating_bases=OperatingBases.default_for_aircraft(aircraft),
            female_pilot_percentage=0,
            pilot_pool=[],
            coalition=self.coalition,
            flight_db=self.game.db.flights,
            settings=self.game.settings,
            location=base,
        )
        squadron.current_roster = pilots
        squadron.available_pilots = list(pilots)
        squadron.owned_aircraft = 2
        squadron.untasked_aircraft = 2
        self.coalition.air_wing.add_squadron(squadron)
        return squadron
