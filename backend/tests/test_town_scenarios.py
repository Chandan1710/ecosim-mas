"""The seven home-page scenarios: each one runs, and the special rules (lockdown, rationing,
disaster damage, boom-then-bust prices) do what they say."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from town.engine import TownSimulation
from town.scenarios import HEADLINES, SCENARIO_ORDER, SCENARIOS
from town.world import PLACES


def run_sim(name, days=7, n=12, seed=3):
    sc = SCENARIOS[name]
    sim = TownSimulation(shock=sc.shock, headlines=list(sc.headlines), n_agents=n, seed=seed, days=days,
                         title=sc.title, pace="fast", rules=sc.rules)

    async def go():
        return [ev async for ev in sim.run()]
    return sim, asyncio.run(go())


def test_the_seven_scenarios():
    assert SCENARIO_ORDER == ["severe", "pandemic", "war", "disaster", "hyperinflation", "none", "lockdown"]
    assert set(SCENARIOS) == set(HEADLINES)
    for sc in SCENARIOS.values():
        assert sc.title and sc.blurb


@pytest.mark.parametrize("name", SCENARIO_ORDER)
def test_every_scenario_runs(name):
    _, events = run_sim(name, days=5, n=8)
    assert events[-1]["type"] == "run_end"


def test_lockdown_keeps_people_home_and_shuts_places():
    sim, events = run_sim("lockdown", days=6)
    onset = sim.econ.onset_day
    essential = set(SCENARIOS["lockdown"].rules.essential)
    for ev in events:
        if ev["type"] == "move" and ev["day"] >= onset:
            place = PLACES[ev["to"]]
            assert place.kind == "home" or place.id in essential, (ev["day"], ev["agent"], ev["to"])
    texts = [e["text"] for e in events if e["type"] == "action" and e["day"] >= onset]
    assert any("lockdown" in t.lower() for t in texts)
    assert not sim.econ.place_open(PLACES["mall"], onset) and sim.econ.place_open(PLACES["pharmacy"], onset)
    assert sim.econ.place_open(PLACES["mall"], 1) or PLACES["mall"].is_open(sim.econ.weekday(1))


def test_rationing_limits_food_stock():
    sim, _ = run_sim("pandemic", days=7)
    econ = sim.econ                           # day 8 of a 7-day run: the shock is at full strength
    needy = next(a for a in sim.agents.values() if a.daily_grocery_need > 0)
    needy.pantry_days = 0.0
    cap = econ._purchase_cap(needy, "groceries", econ.price_multiplier("groceries"))
    days_on_sale = cap / (needy.daily_grocery_need * econ.price_multiplier("groceries"))
    assert days_on_sale < 5                   # was up to 30 days of stock before the shortage
    assert econ.price_multiplier("groceries") > 1.5


def test_disaster_closes_places_and_costs_repairs():
    sim, events = run_sim("disaster", days=7)
    econ = sim.econ
    assert not econ.place_open(PLACES["school"], econ.onset_day) and econ.place_open(PLACES["school"], econ.onset_day + 4)
    losses = [e for e in events if e["type"] == "action" and "repairs cost" in e["text"]]
    homes = {a.id for a in sim.agents.values() if a.home in ("labour_colony", "old_town")}
    assert losses and {e["agent"] for e in losses} <= homes
    assert econ.damage_done


def test_hyperinflation_then_deflation():
    sim, events = run_sim("hyperinflation", days=9)
    prices = [e["prices"]["groceries"] for e in events if e["type"] == "day_start"]
    assert max(prices) > 2.0                  # prices explode
    assert prices[-1] < max(prices) - 0.5     # then fall back hard
    assert min(prices) >= 0.4


def test_baseline_has_no_rules():
    assert SCENARIOS["none"].rules.describe() == []
    assert SCENARIOS["none"].shock.is_zero
