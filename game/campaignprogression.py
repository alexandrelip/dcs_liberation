from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .campaignevents import (
    CampaignEventKind,
    CampaignEventQueue,
    ScheduledCampaignEvent,
)

CAMPAIGN_PERIOD = timedelta(hours=6)
TRANSFER_POLL_INTERVAL = timedelta(minutes=5)
GROUND_COMBAT_INTERVAL = timedelta(minutes=30)
EVENT_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class CampaignProgressionResult:
    events: tuple[ScheduledCampaignEvent, ...] = ()

    def count(self, kind: CampaignEventKind) -> int:
        return sum(event.kind is kind for event in self.events)

    @property
    def income_periods(self) -> int:
        return self.count(CampaignEventKind.INCOME)

    @property
    def ato_replan_periods(self) -> int:
        return self.count(CampaignEventKind.ATO_REPLAN)


@dataclass
class CampaignProgression:
    last_update: datetime
    event_queue: CampaignEventQueue = field(default_factory=CampaignEventQueue)
    ato_replan_interval: timedelta | None = None
    _legacy_ato_replan_elapsed: timedelta = field(default_factory=timedelta)
    event_schema_version: int = EVENT_SCHEMA_VERSION

    def __setstate__(self, state: dict[str, Any]) -> None:
        last_update = state["last_update"]
        if "event_queue" not in state:
            queue = CampaignEventQueue()
            income_elapsed = state.get("income_elapsed", timedelta())
            income_remainder = income_elapsed % CAMPAIGN_PERIOD
            income_delay = (
                CAMPAIGN_PERIOD - income_remainder
                if income_remainder
                else CAMPAIGN_PERIOD
            )
            self._schedule_fixed_events(
                queue,
                last_update,
                income_due_at=last_update + income_delay,
            )
            state["event_queue"] = queue
            state["_legacy_ato_replan_elapsed"] = state.get(
                "ato_replan_elapsed", timedelta()
            )
        elif state.get("event_schema_version", 1) < EVENT_SCHEMA_VERSION:
            queue = state["event_queue"]
            if state.get("event_schema_version", 1) < 2:
                queue.remove_kind(CampaignEventKind.LOGISTICS)
                queue.remove_kind(CampaignEventKind.REPLENISHMENT)
                queue.schedule(
                    CampaignEventKind.LOGISTICS,
                    last_update + TRANSFER_POLL_INTERVAL,
                    interval=TRANSFER_POLL_INTERVAL,
                )
                queue.schedule(
                    CampaignEventKind.REPLENISHMENT,
                    last_update + CAMPAIGN_PERIOD,
                    interval=CAMPAIGN_PERIOD,
                )
            queue.remove_kind(CampaignEventKind.GROUND_COMBAT)
            queue.schedule(
                CampaignEventKind.GROUND_COMBAT,
                last_update + GROUND_COMBAT_INTERVAL,
                interval=GROUND_COMBAT_INTERVAL,
            )
        state.setdefault("ato_replan_interval", None)
        state.setdefault("_legacy_ato_replan_elapsed", timedelta())
        state["event_schema_version"] = EVENT_SCHEMA_VERSION
        state.pop("income_elapsed", None)
        state.pop("ato_replan_elapsed", None)
        self.__dict__.update(state)

    @classmethod
    def starting_at(cls, time: datetime) -> CampaignProgression:
        progression = cls(last_update=time)
        cls._schedule_fixed_events(progression.event_queue, time)
        return progression

    @staticmethod
    def _schedule_fixed_events(
        queue: CampaignEventQueue,
        time: datetime,
        *,
        income_due_at: datetime | None = None,
    ) -> None:
        queue.schedule(
            CampaignEventKind.LOGISTICS,
            time + TRANSFER_POLL_INTERVAL,
            interval=TRANSFER_POLL_INTERVAL,
        )
        queue.schedule(
            CampaignEventKind.REPLENISHMENT,
            time + CAMPAIGN_PERIOD,
            interval=CAMPAIGN_PERIOD,
        )
        queue.schedule(
            CampaignEventKind.INCOME,
            income_due_at or time + CAMPAIGN_PERIOD,
            interval=CAMPAIGN_PERIOD,
        )
        queue.schedule(
            CampaignEventKind.WEATHER,
            time + CAMPAIGN_PERIOD,
            interval=CAMPAIGN_PERIOD,
        )
        queue.schedule(
            CampaignEventKind.GROUND_COMBAT,
            time + GROUND_COMBAT_INTERVAL,
            interval=GROUND_COMBAT_INTERVAL,
        )
        queue.schedule(
            CampaignEventKind.FRONT_LINE,
            time + CAMPAIGN_PERIOD,
            interval=CAMPAIGN_PERIOD,
        )

    def synchronize(self, time: datetime) -> None:
        """Align recurring events with legacy turn processing."""
        self.last_update = time
        self.event_queue = CampaignEventQueue()
        self._schedule_fixed_events(self.event_queue, time)
        self.ato_replan_interval = None
        self._legacy_ato_replan_elapsed = timedelta()

    def _configure_ato_replanning(self, interval: timedelta) -> None:
        if interval <= timedelta():
            raise ValueError("ATO replan interval must be positive")
        if self.ato_replan_interval == interval:
            return

        self.event_queue.remove_kind(CampaignEventKind.ATO_REPLAN)
        elapsed = self._legacy_ato_replan_elapsed % interval
        delay = interval - elapsed if elapsed else interval
        self.event_queue.schedule(
            CampaignEventKind.ATO_REPLAN,
            self.last_update + delay,
            interval=interval,
        )
        self.ato_replan_interval = interval
        self._legacy_ato_replan_elapsed = timedelta()

    def advance_to(
        self,
        time: datetime,
        ato_replan_interval: timedelta,
    ) -> CampaignProgressionResult:
        if time < self.last_update:
            raise ValueError(
                f"Campaign time cannot move backwards from {self.last_update} to {time}"
            )
        self._configure_ato_replanning(ato_replan_interval)
        events = self.event_queue.pop_due(time)
        self.last_update = time
        return CampaignProgressionResult(events)
