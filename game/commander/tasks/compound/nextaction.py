from collections.abc import Iterator
from dataclasses import dataclass

from game.commander.tasks.compound.attackairinfrastructure import (
    AttackAirInfrastructure,
)
from game.commander.tasks.compound.attackbuildings import AttackBuildings
from game.commander.tasks.compound.attackbattlepositions import AttackBattlePositions
from game.commander.tasks.compound.capturebases import CaptureBases
from game.commander.tasks.compound.defendbases import DefendBases
from game.commander.tasks.compound.degradeiads import DegradeIads
from game.commander.tasks.compound.interdictreinforcements import (
    InterdictReinforcements,
)
from game.commander.tasks.compound.protectairspace import ProtectAirSpace
from game.commander.tasks.compound.theatersupport import TheaterSupport
from game.commander.theaterstate import TheaterState
from game.htn import CompoundTask, Method


@dataclass(frozen=True)
class PlanNextAction(CompoundTask[TheaterState]):
    aircraft_cold_start: bool

    def each_valid_method(self, state: TheaterState) -> Iterator[Method[TheaterState]]:
        settings = state.context.settings
        prioritized = [
            (settings.priority_theater_support, 0, TheaterSupport()),
            (settings.priority_air_defense, 1, ProtectAirSpace()),
            (settings.priority_capture, 2, CaptureBases()),
            (settings.priority_defense, 3, DefendBases()),
            (settings.priority_interdiction, 4, InterdictReinforcements()),
            (settings.priority_battlefield, 5, AttackBattlePositions()),
            (
                settings.priority_air_infrastructure,
                6,
                AttackAirInfrastructure(self.aircraft_cold_start),
            ),
            (settings.priority_strike, 7, AttackBuildings()),
            (settings.priority_iads, 8, DegradeIads()),
        ]
        for priority, _, task in sorted(
            prioritized,
            key=lambda item: (-item[0], item[1]),
        ):
            if priority > 0:
                yield [task]
