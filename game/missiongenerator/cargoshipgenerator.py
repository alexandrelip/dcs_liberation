from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING

from dcs import Mission
from dcs.unitgroup import ShipGroup

from game.transfers import CargoShip
from game.unitmap import UnitMap
from game.utils import knots
from .missiondata import MissionData

if TYPE_CHECKING:
    from game import Game


class CargoShipGenerator:
    def __init__(
        self,
        mission: Mission,
        game: Game,
        unit_map: UnitMap,
        mission_data: MissionData,
    ) -> None:
        self.mission = mission
        self.game = game
        self.unit_map = unit_map
        self.mission_data = mission_data
        self.count = itertools.count()

    def generate(self) -> None:
        # Reset the count to make generation deterministic.
        for coalition in self.game.coalitions:
            for ship in coalition.transfers.cargo_ships:
                coalition_name = "blue" if ship.player_owned else "red"
                if (
                    self.mission_data.active_ship_units[coalition_name]
                    >= self.game.settings.perf_max_active_ships_per_coalition
                    or self.mission_data.selected_tactical_units[coalition_name]
                    >= self.game.settings.perf_max_active_units_per_coalition
                ):
                    logging.info(
                        "Keeping cargo ship %s abstract to respect the active-ship "
                        "budget",
                        ship.name,
                    )
                    continue
                self.generate_cargo_ship(ship)
                self.mission_data.active_ship_units[coalition_name] += 1
                self.mission_data.selected_tactical_units[coalition_name] += 1

    def generate_cargo_ship(self, ship: CargoShip) -> ShipGroup:
        coalition = self.game.coalition_for(ship.player_owned)
        country = self.mission.country(coalition.country_name)
        waypoints = ship.route
        group = self.mission.ship_group(
            country,
            ship.name,
            coalition.faction.cargo_ship.dcs_unit_type,
            position=waypoints[0],
            group_size=1,
        )
        for waypoint in waypoints[1:]:
            # 12 knots is very slow but it's also nearly the max allowed by DCS for this
            # type of ship.
            group.add_waypoint(waypoint, speed=knots(CargoShip.SPEED_KNOTS).kph)
        self.unit_map.add_cargo_ship(group, ship)
        return group
