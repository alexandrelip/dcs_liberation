from datetime import datetime, timedelta

import pytest

from game.campaignhistory import CampaignEventCategory, CampaignHistory

START = datetime(2000, 1, 1)


def test_history_returns_newest_entries_first() -> None:
    history = CampaignHistory()
    history.record(START, CampaignEventCategory.ATO, "First")
    history.record(
        START + timedelta(minutes=1),
        CampaignEventCategory.LOGISTICS,
        "Second",
    )

    assert [entry.title for entry in history.recent()] == ["Second", "First"]


def test_history_is_bounded() -> None:
    history = CampaignHistory()

    for index in range(CampaignHistory.MAX_ENTRIES + 3):
        history.record(
            START + timedelta(seconds=index),
            CampaignEventCategory.COMBAT,
            str(index),
        )

    assert len(history.entries) == CampaignHistory.MAX_ENTRIES
    assert history.entries[0].title == "3"


def test_history_validates_limit() -> None:
    history = CampaignHistory()

    assert history.recent(0) == []
    with pytest.raises(ValueError, match="cannot be negative"):
        history.recent(-1)
