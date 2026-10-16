from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import ClassVar


class CampaignEventCategory(Enum):
    ATO = "ATO"
    COMBAT = "Combat"
    ECONOMY = "Economy"
    LOGISTICS = "Logistics"
    WEATHER = "Weather"


@dataclass(frozen=True)
class CampaignHistoryEntry:
    occurred_at: datetime
    category: CampaignEventCategory
    title: str
    details: str = ""


@dataclass
class CampaignHistory:
    MAX_ENTRIES: ClassVar[int] = 2_000
    entries: list[CampaignHistoryEntry] = field(default_factory=list)

    def record(
        self,
        occurred_at: datetime,
        category: CampaignEventCategory,
        title: str,
        details: str = "",
    ) -> CampaignHistoryEntry:
        entry = CampaignHistoryEntry(occurred_at, category, title, details)
        self.entries.append(entry)
        overflow = len(self.entries) - self.MAX_ENTRIES
        if overflow > 0:
            del self.entries[:overflow]
        return entry

    def recent(self, limit: int = 100) -> list[CampaignHistoryEntry]:
        if limit < 0:
            raise ValueError("History limit cannot be negative")
        if not limit:
            return []
        return list(reversed(self.entries[-limit:]))
