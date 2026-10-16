from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

CAMPAIGN_PERIOD = timedelta(hours=6)


class IncomeRecipient(Protocol):
    def accrue_income(self, periods: int = 1) -> float: ...


@dataclass(frozen=True)
class CampaignProgressionResult:
    income_periods: int = 0
    ato_replan_periods: int = 0


@dataclass
class CampaignProgression:
    last_update: datetime
    income_elapsed: timedelta = field(default_factory=timedelta)
    ato_replan_elapsed: timedelta = field(default_factory=timedelta)

    def __setstate__(self, state: dict[str, Any]) -> None:
        state.setdefault("ato_replan_elapsed", timedelta())
        self.__dict__.update(state)

    @classmethod
    def starting_at(cls, time: datetime) -> CampaignProgression:
        return cls(last_update=time)

    def synchronize(self, time: datetime) -> None:
        """Align recurring events with legacy turn processing."""
        self.last_update = time
        self.income_elapsed = timedelta()
        self.ato_replan_elapsed = timedelta()

    def advance_to(
        self,
        coalitions: Iterable[IncomeRecipient],
        time: datetime,
        ato_replan_interval: timedelta | None = None,
    ) -> CampaignProgressionResult:
        if time < self.last_update:
            raise ValueError(
                f"Campaign time cannot move backwards from {self.last_update} to {time}"
            )
        if ato_replan_interval is not None and ato_replan_interval <= timedelta():
            raise ValueError("ATO replan interval must be positive")

        elapsed = time - self.last_update
        self.income_elapsed += elapsed
        self.ato_replan_elapsed += elapsed
        self.last_update = time
        income_periods, self.income_elapsed = divmod(
            self.income_elapsed, CAMPAIGN_PERIOD
        )
        ato_replan_periods = 0
        if ato_replan_interval is not None:
            ato_replan_periods, self.ato_replan_elapsed = divmod(
                self.ato_replan_elapsed, ato_replan_interval
            )

        if income_periods:
            for coalition in coalitions:
                coalition.accrue_income(income_periods)

        return CampaignProgressionResult(
            income_periods=income_periods,
            ato_replan_periods=ato_replan_periods,
        )
