from game.sim.simulationresults import SimulationResults


def test_combat_events_are_recorded_for_campaign_history() -> None:
    results = SimulationResults()

    results.record_combat("Air combat", "Blue power 10; red power 8")

    assert len(results.combat_events) == 1
    assert results.combat_events[0].title == "Air combat"
    assert results.combat_events[0].details == "Blue power 10; red power 8"
