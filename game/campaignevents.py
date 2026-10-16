from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import Any


class CampaignEventKind(Enum):
    LOGISTICS = "logistics"
    INCOME = "income"
    WEATHER = "weather"
    FRONT_LINE = "front-line"
    ATO_REPLAN = "ato-replan"


class CampaignEventPriority(IntEnum):
    LOGISTICS = 10
    INCOME = 20
    WEATHER = 30
    FRONT_LINE = 40
    ATO_REPLAN = 100


EVENT_PRIORITIES = {
    CampaignEventKind.LOGISTICS: CampaignEventPriority.LOGISTICS,
    CampaignEventKind.INCOME: CampaignEventPriority.INCOME,
    CampaignEventKind.WEATHER: CampaignEventPriority.WEATHER,
    CampaignEventKind.FRONT_LINE: CampaignEventPriority.FRONT_LINE,
    CampaignEventKind.ATO_REPLAN: CampaignEventPriority.ATO_REPLAN,
}


@dataclass(order=True, frozen=True)
class ScheduledCampaignEvent:
    due_at: datetime
    priority: int
    sequence: int
    kind: CampaignEventKind = field(compare=False)
    interval: timedelta | None = field(default=None, compare=False)


@dataclass
class CampaignEventQueue:
    _events: list[ScheduledCampaignEvent] = field(default_factory=list)
    _next_sequence: int = 0

    def __setstate__(self, state: dict[str, Any]) -> None:
        state.setdefault("_events", [])
        state.setdefault(
            "_next_sequence",
            max((event.sequence for event in state["_events"]), default=-1) + 1,
        )
        self.__dict__.update(state)
        heapq.heapify(self._events)

    def schedule(
        self,
        kind: CampaignEventKind,
        due_at: datetime,
        *,
        interval: timedelta | None = None,
    ) -> ScheduledCampaignEvent:
        if interval is not None and interval <= timedelta():
            raise ValueError("Campaign event interval must be positive")
        event = ScheduledCampaignEvent(
            due_at=due_at,
            priority=int(EVENT_PRIORITIES[kind]),
            sequence=self._next_sequence,
            kind=kind,
            interval=interval,
        )
        self._next_sequence += 1
        heapq.heappush(self._events, event)
        return event

    def remove_kind(self, kind: CampaignEventKind) -> None:
        self._events = [event for event in self._events if event.kind is not kind]
        heapq.heapify(self._events)

    def pop_due(self, time: datetime) -> tuple[ScheduledCampaignEvent, ...]:
        due = []
        while self._events and self._events[0].due_at <= time:
            event = heapq.heappop(self._events)
            due.append(event)
            if event.interval is not None:
                self.schedule(
                    event.kind,
                    event.due_at + event.interval,
                    interval=event.interval,
                )
        return tuple(due)

    def next_for(self, kind: CampaignEventKind) -> ScheduledCampaignEvent | None:
        matching = (event for event in self._events if event.kind is kind)
        return min(matching, default=None)
