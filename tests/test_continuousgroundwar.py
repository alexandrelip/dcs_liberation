import pickle
from unittest.mock import Mock
from uuid import uuid4

from game.dcs.groundunittype import GroundUnitType
from game.ground_forces.combat_stance import CombatStance
from game.ground_forces.continuouscombat import ContinuousGroundWar
from game.theater.base import Base


def unit_type(name: str, price: int) -> GroundUnitType:
    unit = Mock(spec=GroundUnitType)
    unit.variant_id = name
    unit.price = price
    return unit


def front_line(
    *,
    blue_stance: CombatStance,
    red_stance: CombatStance,
    blue_units: int = 100,
    red_units: int = 100,
) -> tuple[Mock, GroundUnitType, GroundUnitType]:
    blue_type = unit_type("Blue armor", 10)
    red_type = unit_type("Red armor", 10)
    blue = Mock()
    red = Mock()
    blue.id = uuid4()
    red.id = uuid4()
    blue.base = Base()
    red.base = Base()
    blue.base.armor[blue_type] = blue_units
    red.base.armor[red_type] = red_units
    blue.stances = {red.id: blue_stance}
    red.stances = {blue.id: red_stance}
    line = Mock()
    line.id = uuid4()
    line.blue_cp = blue
    line.red_cp = red
    return line, blue_type, red_type


def test_equal_defensive_forces_hold_position() -> None:
    line, _, _ = front_line(
        blue_stance=CombatStance.DEFENSIVE,
        red_stance=CombatStance.DEFENSIVE,
    )

    outcome = ContinuousGroundWar().resolve(line)

    assert outcome.strength_delta == 0
    assert line.blue_cp.base.strength == 1
    assert line.red_cp.base.strength == 1


def test_aggressive_force_advances_against_defender() -> None:
    line, _, _ = front_line(
        blue_stance=CombatStance.AGGRESSIVE,
        red_stance=CombatStance.DEFENSIVE,
    )

    outcome = ContinuousGroundWar().resolve(line)

    assert outcome.strength_delta > 0
    assert line.red_cp.base.strength < 1


def test_retreating_force_gives_up_ground() -> None:
    line, _, _ = front_line(
        blue_stance=CombatStance.RETREAT,
        red_stance=CombatStance.DEFENSIVE,
    )

    outcome = ContinuousGroundWar().resolve(line)

    assert outcome.strength_delta < 0
    assert line.blue_cp.base.strength < 1


def test_attrition_credit_produces_deterministic_unit_losses() -> None:
    line, blue_type, red_type = front_line(
        blue_stance=CombatStance.AGGRESSIVE,
        red_stance=CombatStance.AGGRESSIVE,
    )
    war = ContinuousGroundWar()

    outcomes = [war.resolve(line) for _ in range(4)]

    assert sum(o.blue_losses.get(blue_type, 0) for o in outcomes) == 1
    assert sum(o.red_losses.get(red_type, 0) for o in outcomes) == 1
    assert line.blue_cp.base.total_armor == 99
    assert line.red_cp.base.total_armor == 99


def test_ground_war_state_round_trips_through_save() -> None:
    line, _, _ = front_line(
        blue_stance=CombatStance.AGGRESSIVE,
        red_stance=CombatStance.AGGRESSIVE,
    )
    war = ContinuousGroundWar()
    war.resolve(line)

    restored = pickle.loads(pickle.dumps(war))

    assert restored.attrition_credit == war.attrition_credit


def test_offensive_force_captures_zero_strength_enemy_base() -> None:
    line, _, _ = front_line(
        blue_stance=CombatStance.AGGRESSIVE,
        red_stance=CombatStance.DEFENSIVE,
    )
    line.red_cp.base.strength = 0.001

    outcome = ContinuousGroundWar().resolve(line)

    assert outcome.capture_by_player is True
