from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from game.dcs.aircrafttype import AircraftType
from game.missiongenerator.aircraft.flightdata import FlightData
from game.runways import RunwayData

if TYPE_CHECKING:
    from game.radio.radios import RadioFrequency
    from game.radio.tacan import TacanChannel


@dataclass
class GroupInfo:
    group_name: str
    callsign: str
    freq: RadioFrequency
    blue: bool


@dataclass
class UnitInfo(GroupInfo):
    unit_name: str


@dataclass
class AwacsInfo(GroupInfo):
    """AWACS information for the kneeboard."""

    depature_location: Optional[str]
    start_time: datetime | None
    end_time: datetime | None


@dataclass
class TankerInfo(GroupInfo):
    """Tanker information for the kneeboard."""

    variant: str
    tacan: TacanChannel
    start_time: datetime | None
    end_time: datetime | None


@dataclass
class CarrierInfo(UnitInfo):
    """Carrier information."""

    tacan: TacanChannel


@dataclass
class JtacInfo(UnitInfo):
    """JTAC information."""

    region: str
    code: str


@dataclass
class CargoInfo:
    """Cargo information."""

    unit_type: str = field(default_factory=str)
    spawn_zone: str = field(default_factory=str)
    amount: int = field(default=1)


@dataclass
class LogisticsInfo:
    """Logistics information."""

    pilot_names: list[str]
    transport: AircraftType
    blue: bool

    logistic_unit: str = field(default_factory=str)
    pickup_zone: str = field(default_factory=str)
    drop_off_zone: str = field(default_factory=str)
    target_zone: str = field(default_factory=str)
    cargo: list[CargoInfo] = field(default_factory=list)
    preload: bool = field(default=False)


@dataclass
class DeferredGroundGroup:
    group_name: str
    position_x: float
    position_y: float
    activation_distance: float
    coalition: str
    kind: str
    site_name: str
    unit_count: int


@dataclass
class MissionData:
    awacs: list[AwacsInfo] = field(default_factory=list)
    runways: list[RunwayData] = field(default_factory=list)
    carriers: list[CarrierInfo] = field(default_factory=list)
    briefing_data: list[list[FlightData]] = field(default_factory=list)
    tankers: list[TankerInfo] = field(default_factory=list)
    jtacs: list[JtacInfo] = field(default_factory=list)
    logistics: list[LogisticsInfo] = field(default_factory=list)
    deferred_ground_groups: list[DeferredGroundGroup] = field(default_factory=list)
    activation_anchor_groups: list[str] = field(default_factory=list)
    active_ship_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    active_ground_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    active_infantry_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    deferred_ground_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    deferred_infantry_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    deferred_ship_units: dict[str, int] = field(
        default_factory=lambda: {"blue": 0, "red": 0}
    )
    selected_sam_sites: dict[str, set[str]] = field(
        default_factory=lambda: {"blue": set(), "red": set()}
    )
