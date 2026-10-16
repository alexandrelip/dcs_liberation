from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from game.ato import FlightType
from game.transfers import AirliftPlanner, Convoy, PendingTransfers, TransferOrder

NOW = datetime(2000, 1, 1)


def convoy_transfer(
    *, distance_meters: float = 40_000
) -> tuple[TransferOrder, Convoy, Mock, Mock]:
    start = Mock()
    end = Mock()
    start.distance_to_point.return_value = distance_meters
    origin = Mock(name="Origin", position=start)
    destination = Mock(name="Destination", position=end)
    origin.name = "Origin"
    destination.name = "Destination"
    origin.is_friendly.return_value = True
    origin.convoy_route_to.return_value = (start, end)
    transfer = TransferOrder(origin, destination, {Mock(): 1})
    convoy = Convoy(origin, destination)
    convoy.add_units(transfer)
    return transfer, convoy, origin, destination


def pending_transfers(
    transfer: TransferOrder,
) -> tuple[PendingTransfers, Mock, Mock]:
    transfers: PendingTransfers = object.__new__(PendingTransfers)
    transfers.pending_transfers = [transfer]
    convoys = Mock()
    cargo_ships = Mock()
    transfers.convoys = convoys
    transfers.cargo_ships = cargo_ships
    return transfers, convoys, cargo_ships


def test_convoy_duration_uses_mission_speed_and_route_length() -> None:
    transfer, convoy, _, _ = convoy_transfer(distance_meters=40_000)

    transfer.begin_leg(NOW)

    assert convoy.travel_duration == timedelta(hours=1)
    assert transfer.leg_started_at == NOW
    assert transfer.leg_arrives_at == NOW + timedelta(hours=1)


def test_timed_transfer_waits_for_eta_then_completes() -> None:
    transfer, convoy, origin, destination = convoy_transfer()
    transfer.begin_leg(NOW)
    transfers, convoys, _ = pending_transfers(transfer)

    with patch.object(transfers, "disband_uncompletable_transfers"):
        transfers.perform_transfers(NOW + timedelta(minutes=59))
        assert transfer.position is origin
        assert transfers.pending_transfers == [transfer]

        transfers.perform_transfers(NOW + timedelta(hours=1))

    assert transfer.position is destination
    assert not transfers.pending_transfers
    destination.base.commission_units.assert_called_once_with(transfer.units)
    convoys.remove.assert_called_once_with(convoy, transfer)
    convoys.disband_all.assert_not_called()


def test_legacy_transfer_still_advances_one_leg_per_turn() -> None:
    transfer, _, _, destination = convoy_transfer()
    transfers, convoys, cargo_ships = pending_transfers(transfer)

    with patch.object(transfers, "disband_uncompletable_transfers"):
        transfers.perform_transfers()

    assert transfer.position is destination
    assert not transfers.pending_transfers
    convoys.disband_all.assert_called_once_with()
    cargo_ships.disband_all.assert_called_once_with()


def test_old_transfer_save_gets_empty_leg_timing() -> None:
    transfer: TransferOrder = object.__new__(TransferOrder)

    transfer.__setstate__({"origin": Mock(), "destination": Mock(), "units": {}})

    assert transfer.leg_started_at is None
    assert transfer.leg_arrives_at is None


def test_airlift_range_check_includes_pickup_to_dropoff_leg() -> None:
    home = Mock()
    pickup = Mock()
    drop_off = Mock()
    home.distance_to_point.side_effect = lambda point: 0
    pickup.distance_to_point.return_value = AirliftPlanner.HELO_MAX_RANGE.meters + 1
    drop_off.distance_to_point.return_value = 0
    transfer = Mock()
    transfer.origin.can_operate.return_value = True
    transfer.position.position = pickup
    next_stop = Mock(position=drop_off)
    next_stop.can_operate.return_value = True
    planner: AirliftPlanner = object.__new__(AirliftPlanner)
    planner.transfer = transfer
    planner.next_stop = next_stop
    aircraft = Mock()
    aircraft.capable_of.return_value = True
    aircraft.dcs_unit_type.helicopter = True
    airfield = Mock(position=home)

    assert not planner.compatible_with_mission(aircraft, airfield)
    aircraft.capable_of.assert_called_once_with(FlightType.TRANSPORT)
