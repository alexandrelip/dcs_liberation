from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from game.dcs.groundunittype import GroundUnitType
from game.ground_forces.combat_stance import CombatStance

if TYPE_CHECKING:
    from game.theater import ControlPoint, FrontLine
    from game.theater.base import Base


@dataclass(frozen=True)
class StanceProfile:
    offense: float
    defense: float
    exposure: float
    advance: float


STANCE_PROFILES = {
    CombatStance.DEFENSIVE: StanceProfile(0.25, 1.25, 0.65, 0.0),
    CombatStance.AGGRESSIVE: StanceProfile(1.0, 1.0, 1.0, 1.0),
    CombatStance.RETREAT: StanceProfile(0.1, 0.7, 0.35, -1.0),
    CombatStance.BREAKTHROUGH: StanceProfile(1.4, 0.75, 1.5, 1.5),
    CombatStance.ELIMINATION: StanceProfile(1.25, 0.85, 1.4, 0.75),
    CombatStance.AMBUSH: StanceProfile(0.55, 1.4, 0.6, 0.0),
}

ATTRITION_RATE = 0.005
MAX_STRENGTH_SHIFT = 0.025


@dataclass
class AttritionCredit:
    blue: float = 0.0
    red: float = 0.0


@dataclass(frozen=True)
class GroundCombatOutcome:
    blue_losses: dict[GroundUnitType, int]
    red_losses: dict[GroundUnitType, int]
    strength_delta: float


@dataclass
class ContinuousGroundWar:
    attrition_credit: dict[UUID, AttritionCredit] = field(default_factory=dict)

    def resolve(self, front_line: FrontLine) -> GroundCombatOutcome:
        blue = front_line.blue_cp
        red = front_line.red_cp
        blue_stance = blue.stances[red.id]
        red_stance = red.stances[blue.id]
        blue_profile = STANCE_PROFILES[blue_stance]
        red_profile = STANCE_PROFILES[red_stance]
        blue_value = float(blue.base.total_armor_value)
        red_value = float(red.base.total_armor_value)
        credit = self.attrition_credit.setdefault(front_line.id, AttritionCredit())

        if blue_value and red_value:
            contested_value = min(blue_value, red_value)
            blue_defense = blue_value * blue_profile.defense
            red_defense = red_value * red_profile.defense
            blue_attack = blue_value * blue_profile.offense
            red_attack = red_value * red_profile.offense
            credit.blue += (
                contested_value
                * ATTRITION_RATE
                * self._pressure(red_attack, blue_defense)
                * blue_profile.exposure
            )
            credit.red += (
                contested_value
                * ATTRITION_RATE
                * self._pressure(blue_attack, red_defense)
                * red_profile.exposure
            )

        blue_losses, credit.blue = self._apply_attrition(blue.base, credit.blue)
        red_losses, credit.red = self._apply_attrition(red.base, credit.red)
        strength_delta = self._strength_delta(
            blue,
            red,
            blue_profile,
            red_profile,
        )
        blue.base.affect_strength(strength_delta)
        red.base.affect_strength(-strength_delta)
        return GroundCombatOutcome(blue_losses, red_losses, strength_delta)

    @staticmethod
    def _pressure(attack: float, defense: float) -> float:
        total = attack + defense
        if not total:
            return 0.0
        return attack / total

    @staticmethod
    def _strength_delta(
        blue: ControlPoint,
        red: ControlPoint,
        blue_profile: StanceProfile,
        red_profile: StanceProfile,
    ) -> float:
        blue_value = float(blue.base.total_armor_value)
        red_value = float(red.base.total_armor_value)
        total = blue_value + red_value
        if not total:
            return 0.0
        momentum = (
            blue_value * blue_profile.advance - red_value * red_profile.advance
        ) / total
        return max(
            -MAX_STRENGTH_SHIFT,
            min(MAX_STRENGTH_SHIFT, momentum * MAX_STRENGTH_SHIFT),
        )

    @staticmethod
    def _apply_attrition(
        base: Base, credit: float
    ) -> tuple[dict[GroundUnitType, int], float]:
        losses: dict[GroundUnitType, int] = {}
        while True:
            affordable = [
                unit_type
                for unit_type, count in base.armor.items()
                if count > 0 and unit_type.price <= credit
            ]
            if not affordable:
                return losses, credit
            unit_type = max(
                affordable,
                key=lambda candidate: (candidate.price, candidate.variant_id),
            )
            base.commit_losses({unit_type: 1})
            losses[unit_type] = losses.get(unit_type, 0) + 1
            credit -= unit_type.price
