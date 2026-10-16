from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from game.ato import FlightType
from game.commander.missionproposals import ProposedFlight, ProposedMission
from game.commander.packagefulfiller import PackageFulfiller
from game.profiling import MultiEventTracer
from game.theater import ControlPoint, TheaterGroundObject
from game.utils import nautical_miles

if TYPE_CHECKING:
    from game.ato import Package
    from game.coalition import Coalition
    from game.game import Game
    from game.sim import GameUpdateEvents


OFFENSIVE_TARGET_TASKS = {
    FlightType.TARCAP,
    FlightType.CAS,
    FlightType.STRIKE,
    FlightType.ANTISHIP,
    FlightType.SEAD,
    FlightType.DEAD,
    FlightType.BAI,
    FlightType.SWEEP,
    FlightType.OCA_RUNWAY,
    FlightType.OCA_AIRCRAFT,
    FlightType.AIR_ASSAULT,
}

DEFENSIVE_TARGET_TASKS = {
    FlightType.BARCAP,
    FlightType.INTERCEPTION,
    FlightType.AEWC,
    FlightType.REFUELING,
    FlightType.TRANSPORT,
    FlightType.FERRY,
}

QRA_RANGE = nautical_miles(100)


@dataclass(frozen=True)
class CancelledPackage:
    package: Package
    reason: str


class ReactiveAto:
    @classmethod
    def prune_invalid_packages(
        cls,
        game: Game,
        coalition: Coalition,
        events: GameUpdateEvents,
    ) -> list[CancelledPackage]:
        cancelled = []
        threatened = set(cls.threatened_control_points(game, coalition))
        for package in list(coalition.ato.packages):
            reason = cls.invalid_reason(package, coalition.player)
            if (
                reason is None
                and package.primary_task is FlightType.INTERCEPTION
                and package.all_flights_waiting_for_start()
                and package.target not in threatened
            ):
                reason = f"no hostile aircraft threaten {package.target}"
            if reason is None:
                continue
            events.delete_flights_in_package(package)
            coalition.ato.remove_package(package)
            cancelled.append(CancelledPackage(package, reason))
        return cancelled

    @staticmethod
    def invalid_reason(package: Package, player: bool) -> str | None:
        if not package.flights:
            return "package has no flights"
        if not package.all_flights_waiting_for_start():
            return None

        for flight in package.flights:
            if flight.departure.captured != player:
                return f"departure {flight.departure} changed ownership"
            if not flight.is_helo and not flight.departure.runway_is_operational():
                return f"departure runway at {flight.departure} is unavailable"

        target = package.target
        task = package.primary_task
        if isinstance(target, TheaterGroundObject) and target.is_dead:
            return f"target {target} has been destroyed"

        if task is None:
            return "package has no primary task"
        if task in OFFENSIVE_TARGET_TASKS and target.is_friendly(player):
            return f"target {target} is now friendly"
        if task in DEFENSIVE_TARGET_TASKS and not target.is_friendly(player):
            return f"support destination {target} is no longer friendly"
        if (
            task is FlightType.OCA_RUNWAY
            and isinstance(target, ControlPoint)
            and not target.runway_is_operational()
        ):
            return f"runway at {target} is already disabled"
        return None

    @classmethod
    def plan_interceptions(
        cls,
        game: Game,
        coalition: Coalition,
        now: datetime,
    ) -> list[Package]:
        planned = []
        existing_targets = {
            package.target
            for package in coalition.ato.packages
            if package.primary_task is FlightType.INTERCEPTION
        }
        for control_point in cls.threatened_control_points(game, coalition):
            if control_point in existing_targets:
                continue
            fulfiller = PackageFulfiller(
                coalition,
                game.theater,
                game.db.flights,
                game.settings,
            )
            mission = ProposedMission(
                control_point,
                [ProposedFlight(FlightType.INTERCEPTION, 2)],
                asap=True,
            )
            with MultiEventTracer() as tracer:
                package = fulfiller.plan_mission(
                    mission,
                    purchase_multiplier=1,
                    now=now,
                    tracer=tracer,
                )
            if package is None:
                continue
            package.auto_asap = True
            package.set_tot_asap(now)
            coalition.ato.add_package(package)
            existing_targets.add(control_point)
            planned.append(package)
        return planned

    @staticmethod
    def threatened_control_points(
        game: Game,
        coalition: Coalition,
    ) -> list[ControlPoint]:
        hostile_flights = itertools.chain.from_iterable(
            package.flights for package in coalition.opponent.ato.packages
        )
        hostile_positions = [
            flight.position()
            for flight in hostile_flights
            if flight.state.in_flight and flight.alive
        ]
        if not hostile_positions:
            return []

        threatened = []
        for control_point in game.theater.control_points_for(coalition.player):
            if not control_point.runway_is_operational():
                continue
            if any(
                control_point.position.distance_to_point(position) <= QRA_RANGE.meters
                for position in hostile_positions
            ):
                threatened.append(control_point)
        return threatened
