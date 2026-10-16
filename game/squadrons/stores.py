from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from game.ato.loadouts import Loadout
from game.data.weapons import Pylon, Weapon
from game.dcs.aircrafttype import AircraftType
from game.factions.faction import Faction


@dataclass
class SquadronStores:
    stock: dict[str, int] = field(default_factory=dict)
    capacity: dict[str, int] = field(default_factory=dict)

    def available(self, weapon: Weapon, initial_capacity: int) -> int:
        self._ensure_weapon(weapon, initial_capacity)
        return self.stock[weapon.clsid]

    def claim_loadout(
        self,
        loadout: Loadout,
        aircraft: AircraftType,
        campaign_date: date,
        faction: Faction,
        initial_capacity: int,
    ) -> tuple[Loadout, dict[str, int]]:
        selected: dict[int, Weapon | None] = {}
        reservations: Counter[str] = Counter()
        for pylon_number, requested in loadout.pylons.items():
            if requested is None:
                continue
            pylon = Pylon.for_aircraft(aircraft, pylon_number)
            chosen = self._available_fallback(
                requested,
                pylon,
                campaign_date,
                faction,
                initial_capacity,
                reservations,
            )
            if chosen is None:
                continue
            selected[pylon_number] = chosen
            if chosen.clsid != "<CLEAN>":
                reservations[chosen.clsid] += 1

        for clsid, count in reservations.items():
            self.stock[clsid] -= count
        return (
            Loadout(
                loadout.name,
                selected,
                loadout.date,
                loadout.is_custom,
            ),
            dict(reservations),
        )

    def refund(self, reservations: dict[str, int]) -> None:
        for clsid, count in reservations.items():
            if count < 0:
                raise ValueError("Cannot refund a negative weapon quantity")
            capacity = self.capacity.get(clsid, count)
            self.capacity[clsid] = capacity
            self.stock[clsid] = min(capacity, self.stock.get(clsid, 0) + count)

    def resupply(self, units_per_weapon: int) -> int:
        if units_per_weapon < 0:
            raise ValueError("Weapon resupply cannot be negative")
        delivered = 0
        for clsid, capacity in self.capacity.items():
            previous = self.stock.get(clsid, 0)
            updated = min(capacity, previous + units_per_weapon)
            self.stock[clsid] = updated
            delivered += updated - previous
        return delivered

    def _ensure_weapon(self, weapon: Weapon, initial_capacity: int) -> None:
        if initial_capacity <= 0:
            raise ValueError("Initial weapon capacity must be positive")
        if weapon.clsid not in self.capacity:
            self.capacity[weapon.clsid] = initial_capacity
            self.stock[weapon.clsid] = initial_capacity

    def _available_fallback(
        self,
        requested: Weapon,
        pylon: Pylon,
        campaign_date: date,
        faction: Faction,
        initial_capacity: int,
        pending: Counter[str],
    ) -> Weapon | None:
        seen = set()
        for fallback in requested.fallbacks:
            if fallback.clsid in seen:
                continue
            seen.add(fallback.clsid)
            if not pylon.can_equip(fallback):
                continue
            if not fallback.available_on(campaign_date, faction):
                continue
            if fallback.clsid == "<CLEAN>":
                return fallback
            available = self.available(fallback, initial_capacity)
            if available - pending[fallback.clsid] > 0:
                return fallback
        return None
