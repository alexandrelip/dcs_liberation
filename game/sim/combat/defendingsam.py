from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from game.ato.flightstate import InCombat
from game.settings.settings import CombatResolutionMethod
from .combatpower import deterministic_roll, sam_loss_probability
from .frozencombat import FrozenCombat
from .. import GameUpdateEvents

if TYPE_CHECKING:
    from game.ato import Flight
    from game.theater import TheaterGroundObject
    from ..simulationresults import SimulationResults


class DefendingSam(FrozenCombat):
    def __init__(
        self,
        freeze_duration: timedelta,
        flight: Flight,
        air_defenses: list[TheaterGroundObject],
    ) -> None:
        super().__init__(freeze_duration)
        self.flight = flight
        self.air_defenses = air_defenses

    def because(self) -> str:
        sams = ", ".join(str(d) for d in self.air_defenses)
        return f"{self.flight} is engaged by enemy air defenses: {sams}"

    def describe(self) -> str:
        return "engaged by enemy air defenses"

    def iter_flights(self) -> Iterator[Flight]:
        yield self.flight

    def resolve(
        self,
        results: SimulationResults,
        events: GameUpdateEvents,
        time: datetime,
        elapsed_time: timedelta,
        resolution_method: CombatResolutionMethod,
    ) -> None:
        assert isinstance(self.flight.state, InCombat)

        if resolution_method is CombatResolutionMethod.SKIP:
            self.flight.state.exit_combat(events, time, elapsed_time)
            return

        loss_probability = sam_loss_probability(self.flight, self.air_defenses)
        if deterministic_roll(self.id) < loss_probability:
            logging.debug(f"Air defense combat auto-resolved with {self.flight} lost")
            self.flight.kill(results, events)
            outcome = "flight lost"
        else:
            logging.debug(
                "%s survived air defenses (loss probability %.1f%%)",
                self.flight,
                loss_probability * 100,
            )
            self.flight.state.exit_combat(events, time, elapsed_time)
            outcome = "flight survived"
        results.record_combat(
            "SAM engagement auto-resolved",
            (
                f"{self.flight}; defenses={len(self.air_defenses)}; "
                f"loss probability={loss_probability:.1%}; {outcome}"
            ),
        )
