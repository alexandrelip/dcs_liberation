from datetime import datetime
from unittest.mock import Mock, patch

from game import Game
from game.groundunitorders import GroundUnitOrders


def test_orders_without_reinforcement_source_are_refunded_and_stop() -> None:
    destination = Mock(captured=True, name="Isolated Base")
    orders = GroundUnitOrders(destination)
    unit_type = Mock(price=10)
    orders.order({unit_type: 2})
    coalition = Mock()
    game = Mock(spec=Game)
    game.coalition_for.return_value = coalition

    with patch.object(
        orders,
        "find_ground_unit_source",
        return_value=None,
    ):
        orders.process(game, datetime(2000, 1, 1))

    coalition.adjust_budget.assert_called_once_with(20)
    destination.base.commission_units.assert_not_called()
    assert not orders.units
