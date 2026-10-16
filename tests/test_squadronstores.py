from datetime import date
from typing import cast
from unittest.mock import Mock, patch

import pytest

from game.ato.loadouts import Loadout
from game.ato.flight import Flight
from game.data.weapons import Weapon
from game.dcs.aircrafttype import AircraftType
from game.factions.faction import Faction
from game.squadrons.stores import SquadronStores
from game.missiongenerator.missiongenerator import MissionGenerator

TODAY = date(2000, 1, 1)


def weapon(clsid: str) -> Weapon:
    store = Mock(spec=Weapon, clsid=clsid)
    store.fallbacks = [store]
    store.available_on.return_value = True
    return cast(Weapon, store)


def claim(
    stores: SquadronStores,
    loadout: Loadout,
) -> tuple[Loadout, dict[str, int]]:
    pylon = Mock()
    pylon.can_equip.return_value = True
    with patch(
        "game.squadrons.stores.Pylon.for_aircraft",
        return_value=pylon,
    ):
        return stores.claim_loadout(
            loadout,
            Mock(spec=AircraftType),
            TODAY,
            Mock(spec=Faction),
            initial_capacity=2,
        )


def test_store_claim_is_atomic_across_repeated_pylons() -> None:
    missile = weapon("MISSILE")
    stores = SquadronStores()
    loadout = Loadout("Two missiles", {1: missile, 2: missile}, TODAY)

    selected, reservations = claim(stores, loadout)

    assert selected.pylons == {1: missile, 2: missile}
    assert reservations == {"MISSILE": 2}
    assert stores.stock["MISSILE"] == 0


def test_depleted_weapon_uses_compatible_fallback() -> None:
    requested = weapon("ADVANCED")
    fallback = weapon("LEGACY")
    cast(Mock, requested).fallbacks = [requested, fallback]
    stores = SquadronStores(
        stock={"ADVANCED": 0},
        capacity={"ADVANCED": 2},
    )

    selected, reservations = claim(
        stores,
        Loadout("Fallback", {1: requested}, TODAY),
    )

    assert selected.pylons == {1: fallback}
    assert reservations == {"LEGACY": 1}


def test_pylon_is_empty_when_no_compatible_store_is_available() -> None:
    requested = weapon("EMPTY")
    stores = SquadronStores(stock={"EMPTY": 0}, capacity={"EMPTY": 2})

    selected, reservations = claim(
        stores,
        Loadout("Empty", {1: requested}, TODAY),
    )

    assert selected.pylons == {}
    assert reservations == {}


def test_refund_and_resupply_never_exceed_capacity() -> None:
    stores = SquadronStores(
        stock={"A": 0},
        capacity={"A": 3},
    )

    stores.refund({"A": 2})
    delivered = stores.resupply(5)

    assert stores.stock["A"] == 3
    assert delivered == 1


def test_invalid_store_quantities_are_rejected() -> None:
    stores = SquadronStores()

    with pytest.raises(ValueError, match="negative"):
        stores.refund({"A": -1})
    with pytest.raises(ValueError, match="negative"):
        stores.resupply(-1)


def test_cancelled_unlaunched_flight_refunds_reserved_weapons() -> None:
    flight: Flight = object.__new__(Flight)
    flight.state = Mock(cancelable=True)
    flight.weapon_reservations = {"A": 2}
    flight.reserved_loadouts = [Mock()]
    flight.roster = Mock(max_size=1)
    flight.squadron = Mock()

    flight.return_pilots_and_aircraft()

    flight.squadron.weapon_stores.refund.assert_called_once_with({"A": 2})
    assert flight.weapon_reservations == {}
    assert flight.reserved_loadouts is None


def test_mission_reservation_rolls_back_as_one_transaction() -> None:
    first = Mock(alive=True)
    first.reserve_weapon_loadouts.return_value = True
    second = Mock(alive=True)
    second.reserve_weapon_loadouts.side_effect = RuntimeError("invalid pylon")
    package = Mock(flights=[first, second])
    coalition = Mock()
    coalition.ato.packages = [package]
    generator: MissionGenerator = object.__new__(MissionGenerator)
    generator.game = Mock()
    generator.game.settings.turnless_mode = True
    generator.game.settings.enable_squadron_weapon_limits = True
    generator.game.coalitions = [coalition]

    with pytest.raises(RuntimeError, match="invalid pylon"):
        generator.reserve_weapon_loadouts()

    first.refund_weapon_reservations.assert_called_once_with()
