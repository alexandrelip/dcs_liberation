from datetime import datetime, timedelta
import pickle

import pytest

from game.campaignevents import CampaignEventKind, CampaignEventQueue

START = datetime(2000, 1, 1)


def test_events_are_ordered_by_time_priority_and_sequence() -> None:
    queue = CampaignEventQueue()
    queue.schedule(CampaignEventKind.ATO_REPLAN, START)
    queue.schedule(CampaignEventKind.WEATHER, START)
    queue.schedule(CampaignEventKind.LOGISTICS, START)
    queue.schedule(CampaignEventKind.REPLENISHMENT, START)
    queue.schedule(CampaignEventKind.INCOME, START)
    queue.schedule(CampaignEventKind.FRONT_LINE, START)

    due = queue.pop_due(START)

    assert [event.kind for event in due] == [
        CampaignEventKind.LOGISTICS,
        CampaignEventKind.REPLENISHMENT,
        CampaignEventKind.INCOME,
        CampaignEventKind.WEATHER,
        CampaignEventKind.FRONT_LINE,
        CampaignEventKind.ATO_REPLAN,
    ]


def test_recurring_events_catch_up_without_clock_drift() -> None:
    queue = CampaignEventQueue()
    interval = timedelta(minutes=15)
    queue.schedule(
        CampaignEventKind.ATO_REPLAN,
        START + interval,
        interval=interval,
    )

    due = queue.pop_due(START + timedelta(minutes=46))
    next_event = queue.next_for(CampaignEventKind.ATO_REPLAN)

    assert [event.due_at for event in due] == [
        START + timedelta(minutes=15),
        START + timedelta(minutes=30),
        START + timedelta(minutes=45),
    ]
    assert next_event is not None
    assert next_event.due_at == START + timedelta(minutes=60)


def test_remove_kind_preserves_other_events() -> None:
    queue = CampaignEventQueue()
    queue.schedule(CampaignEventKind.INCOME, START)
    queue.schedule(CampaignEventKind.ATO_REPLAN, START)

    queue.remove_kind(CampaignEventKind.ATO_REPLAN)

    assert [event.kind for event in queue.pop_due(START)] == [CampaignEventKind.INCOME]


def test_queue_round_trips_through_save_serialization() -> None:
    queue = CampaignEventQueue()
    queue.schedule(
        CampaignEventKind.LOGISTICS,
        START + timedelta(hours=6),
        interval=timedelta(hours=6),
    )

    restored = pickle.loads(pickle.dumps(queue))
    due = restored.pop_due(START + timedelta(hours=6))
    next_event = restored.next_for(CampaignEventKind.LOGISTICS)

    assert [event.kind for event in due] == [CampaignEventKind.LOGISTICS]
    assert next_event is not None
    assert next_event.due_at == START + timedelta(hours=12)


def test_recurring_interval_must_be_positive() -> None:
    queue = CampaignEventQueue()

    with pytest.raises(ValueError, match="must be positive"):
        queue.schedule(
            CampaignEventKind.INCOME,
            START,
            interval=timedelta(),
        )
