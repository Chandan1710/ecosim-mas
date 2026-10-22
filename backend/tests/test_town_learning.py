"""Agents that learn from experience: rewards, lessons, trust, persistence, and the effect on behaviour."""

import asyncio
import os

os.environ.setdefault("ECOSIM_EMBEDDER", "hash")

import numpy as np
import pytest

from town.engine import TownSimulation
from town.experience import ExperienceStore
from town.learning import Learner, agent_key, detect_lessons, plan_signature, reward_for
from town.population import generate_population
from town.scenarios import SCENARIOS


@pytest.fixture()
def store(tmp_path):
    return ExperienceStore(f"sqlite:///{tmp_path}/exp.db")


def _run(sc_id, mode, store, days=30):
    sc = SCENARIOS[sc_id]
    sim = TownSimulation(shock=sc.shock, headlines=sc.headlines, days=days, title=sc.title, rules=sc.rules,
                         learning=mode, scenario_id=sc_id, store=store)

    async def go():
        return [ev async for ev in sim.run()]
    return sim, asyncio.run(go())


def _total_reward(events):
    return sum(r["total"] for e in events if e["type"] == "day_end" for r in e["rewards"].values())


# ── the store ───────────────────────────────────────────────────────────────
def test_store_lessons_trust_and_reset(store):
    k = "s7-a01-x"
    store.upsert_lessons(k, [{"key": "food:war", "kind": "do", "text": "Buy food early", "strength": 0.4,
                              "scenario_id": "war", "hint": {"stock_food": 1}, "source": "rule"}], "r1")
    store.upsert_lessons(k, [{"key": "food:war", "kind": "do", "text": "Buy food early", "strength": 0.4,
                              "scenario_id": "war", "hint": {"stock_food": 1}, "source": "rule"}], "r2")
    (l,) = store.lessons_for(k)
    assert l["confirmed"] == 2 and l["strength"] > 0.4          # seen again → stronger
    store.adjust_lessons(k, ["food:war"], -0.2)
    assert store.lessons_for(k)[0]["strength"] < l["strength"]
    t = store.update_trust(k, "s7-a02-y", "Y", +0.2, True, "prices")
    assert t > 0.5 and store.trust_for(k)["s7-a02-y"]["helped"] == 1
    store.reset(k)
    assert store.lessons_for(k) == [] and store.trust_for(k) == {}


# ── rewards ─────────────────────────────────────────────────────────────────
def test_reward_punishes_hunger_and_job_loss_and_rewards_stability():
    a = generate_population(20, 7)[1]
    prev = {"days_hungry": 0, "pantry_days": 5, "medicine_days": 9, "debt": 0, "money": 50000, "employed": True, "fuel_days": 5}
    good, _ = reward_for(a, prev, dict(prev), [])
    hungry, parts = reward_for(a, prev, {**prev, "days_hungry": 1, "pantry_days": 0}, [])
    fired, fp = reward_for(a, prev, {**prev, "employed": False}, [])
    assert good > 0 and hungry < -0.8 and parts["food"] == -1.0
    assert fired <= -1.5 and fp["job"] == -2.0
    miss, _ = reward_for(a, prev, dict(prev), [{"text": "Missed the rent", "ok": False, "data": {"bill": "rent"}}])
    assert miss < good
    assert -3.0 <= min(hungry, fired) and max(good, 0) <= 1.0


def test_every_day_has_a_reward_even_when_not_learning():
    _, evs = _run("severe", "off", None, days=5)
    days = [e for e in evs if e["type"] == "day_end"]
    assert len(days) == 5 and all(set(e["rewards"]) == set(e["agents"]) for e in days)
    assert next(e for e in evs if e["type"] == "run_start")["learning"]["mode"] == "off"


# ── persistence across runs ─────────────────────────────────────────────────
def test_lessons_are_saved_and_used_in_the_next_run(store):
    _, first = _run("lockdown", "learn", store)
    assert next(e for e in first if e["type"] == "run_end")["learning"]["lessons_new"] > 0
    assert store.counts()["town_experience"] == 20 * 30
    sim2, second = _run("lockdown", "learn", store)
    start = next(e for e in second if e["type"] == "run_start")["learning"]
    assert start["mode"] == "learn" and max(start["prior_runs"].values()) == 1 and sum(start["lessons"].values()) > 0
    assert any(e.get("learned") for e in second if e["type"] == "decision")      # lessons shown to deciders
    runs = store.runs_for(agent_key(7, generate_population(20, 7)[0]))
    assert len(runs) == 2


def test_frozen_uses_lessons_but_records_nothing(store):
    _run("lockdown", "learn", store)
    before = store.counts()
    _, evs = _run("lockdown", "frozen", store)
    assert store.counts() == before
    assert any(e.get("learned") for e in evs if e["type"] == "decision")


def test_fresh_mode_ignores_and_records_nothing(store):
    _run("lockdown", "learn", store)
    before = store.counts()
    _, evs = _run("lockdown", "off", store)
    assert store.counts() == before
    assert not any(e.get("learned") for e in evs if e["type"] == "decision")


def test_without_a_database_the_run_still_works():
    _, evs = _run("severe", "learn", None, days=3)
    assert next(e for e in evs if e["type"] == "run_start")["learning"]["mode"] == "off"
    assert evs[-1]["type"] == "run_end"


# ── does it help? ───────────────────────────────────────────────────────────
def test_experience_improves_a_hard_scenario(store):
    """A lockdown catches the offline agents unprepared; after one month of experience the same town does better."""
    _, fresh = _run("lockdown", "off", None)
    _run("lockdown", "learn", store)
    _, trained = _run("lockdown", "frozen", store)
    assert _total_reward(trained) > _total_reward(fresh) + 3.0


# ── lessons and people ──────────────────────────────────────────────────────
def test_lessons_come_from_what_went_wrong():
    from town.learning import _Rec
    a = generate_population(20, 7)[1]
    recs = [_Rec(day=d, state={"food_days": 0.5}, plan={}, outcomes=[{"text": "Ran out of food at home; the family ate less today",
            "ok": False, "importance": 9, "amount": 0, "data": {}, "phase": "evening", "kind": "household"}],
                 reward=-1.3, parts={"food": -1.0}) for d in (10, 11, 12)]
    out = detect_lessons(a, recs, "war", "World war", 5, [], {a.id: a}, {a.id: "k"})
    assert any(l["key"].startswith("food:") and l["hint"].get("stock_food") for l in out)


def test_trust_follows_whether_advice_helped(store):
    sc = SCENARIOS["severe"]
    agents = {a.id: a for a in generate_population(20, 7)}
    ids = list(agents)[:2]
    L = Learner("learn", store, "r1", 7, "severe", sc.title, 5)
    L.begin(agents, {i: {"days_hungry": 0, "pantry_days": 5, "medicine_days": 5, "debt": 0, "money": 9000, "employed": True,
                         "fuel_days": 3} for i in agents})
    a, b = ids
    L.last_day_sig[a][1] = plan_signature({"morning": {"place": "home", "do": "rest", "spend": 0}})
    L.last_day_sig[a][2] = plan_signature({"morning": {"place": "kirana", "do": "shop", "spend": 500}})
    L.log_talk(1, a, b, "prices", {a: "stock up"})
    L.recs[a] = []
    L._settle_talks(2, agents, {i: {"total": 0.5} for i in agents})
    t = store.trust_for(L.keys[a])[L.keys[b]]
    assert t["trust"] > 0.5 and t["helped"] == 1
