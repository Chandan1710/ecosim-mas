"""
Tests for the town of LLM agents (backend/town/). No API keys, Qdrant or
network needed: the LLM is replaced by a fake HTTP transport that answers in
the providers' OpenAI-compatible format, so the real prompt-building,
parsing, rate-limit fallback and engine code all run.
"""

import asyncio
import json
import os
import re

import httpx
import pytest

os.environ.setdefault("ECOSIM_EMBEDDER", "hash")

from simulation.shock import PRESETS, Shock
from town.brain import LLMBrain, normalise_decision
from town.economy import TownEconomy
from town.engine import TownSimulation
from town.llm_pool import LLMPool, LLMUnavailable, Provider, extract_json
from town.memory import HashEmbedder, LocalMemory
from town.population import Loan, generate_population
from town.world import PLACES, validate_map


def run(coro):
    return asyncio.run(coro)


# ── world and population ────────────────────────────────────────────────────

def test_map_is_consistent():
    assert validate_map() == []


def test_population_is_unique_and_seeded():
    a = generate_population(20, seed=3)
    b = generate_population(20, seed=3)
    c = generate_population(20, seed=4)
    assert [x.public_state() for x in a] == [x.public_state() for x in b]
    assert [x.name for x in a] != [x.name for x in c]
    assert len({x.name for x in a}) == 20
    assert len({x.job_key for x in a}) >= 8, "the town should have a real mix of jobs"
    assert not any("persona" in k for k in a[0].public_state()), "agents are individuals, not personas"
    for x in a:
        assert x.money >= 0 and x.home in PLACES
        assert all(k in {y.id for y in a} for k in x.knows)


# ── economy ─────────────────────────────────────────────────────────────────

def test_shock_raises_prices_gradually():
    econ = TownEconomy(PRESETS["severe"], seed=1)
    seen = []
    for d in range(1, 15):
        econ.day = d
        seen.append(econ.price_multiplier("groceries"))
    assert seen[0] == seen[1] == 1.0          # normal before the shock
    assert all(b >= a for a, b in zip(seen, seen[1:]))
    assert seen[-1] == pytest.approx(1.45)
    calm = TownEconomy(Shock(), seed=1)
    calm.day = 20
    assert calm.price_multiplier("groceries") == 1.0


def test_bank_gets_stricter_when_credit_tightens():
    agent = generate_population(20, seed=7)[0]
    agent.credit_score = 680
    agent.loans = []
    loose = TownEconomy(Shock(), seed=1)
    tight = TownEconomy(Shock(credit_tightness=0.5), seed=1)
    tight.day = 20
    assert loose.apply_loan(agent, 5000).ok
    agent2 = generate_population(20, seed=7)[0]
    agent2.credit_score = 680
    agent2.loans = []
    refused = tight.apply_loan(agent2, 5000)
    assert not refused.ok and "credit score" in refused.text


def test_missing_two_emis_is_a_default():
    agent = generate_population(20, seed=7)[0]
    agent.money = 0
    agent.loans = [Loan("vehicle", "bank", 50000, 3000, "monthly", 5), Loan("vehicle", "bank", 1, 1, "monthly", 6)]
    econ = TownEconomy(Shock(), seed=1)
    econ.day = 5
    first = econ.settle_bills(agent, [])
    assert any("Missed" in o.text for o in first) and not agent.loans[0].defaulted
    agent.loans[0].due_day = 6
    econ.day = 6
    second = econ.settle_bills(agent, [])
    assert agent.loans[0].defaulted and any(o.importance == 10 for o in second)


def test_kirana_gives_credit_to_people_the_owner_knows():
    pop = generate_population(20, seed=7)
    agents = {a.id: a for a in pop}
    econ = TownEconomy(Shock(), seed=1)
    owner = econ.owner_of("kirana", agents)
    assert owner is not None
    buyer = next(a for a in pop if a.id != owner.id and a.daily_grocery_need > 0)
    buyer.knows[owner.id] = "shopkeeper"
    buyer.money = 100
    buyer.pantry_days = 0
    out = econ.buy(buyer, PLACES["kirana"], "groceries", 800, owner=owner)
    assert out.ok and buyer.khata_due == pytest.approx(700) and buyer.money == 0


def test_market_stays_open_without_the_agent_vendor():
    pop = generate_population(20, seed=7)
    agents = {a.id: a for a in pop}
    econ = TownEconomy(Shock(), seed=1)
    vendor = econ.owner_of("market", agents)
    assert vendor is not None
    assert econ.shop_open(PLACES["market"], "afternoon", agents)[0]          # other stalls are open
    assert not econ.shop_open(PLACES["kirana"], "afternoon", agents)[0]      # a one-person shop is not
    buyer = next(a for a in pop if a.id != vendor.id and a.daily_grocery_need > 0)
    buyer.pantry_days, buyer.money = 0, 5000
    econ.buy(buyer, PLACES["market"], "groceries", 400, phase="afternoon")
    assert econ.sales_today.get("market", 0) == 0                            # vendor away: their stall sold nothing
    econ.owner_present[("market", "evening")] = True
    econ.buy(buyer, PLACES["market"], "groceries", 400, phase="evening")
    assert econ.sales_today["market"] == pytest.approx(100)                  # their share of the market


# ── memory ──────────────────────────────────────────────────────────────────

def test_retrieval_weighs_importance_recency_and_relevance():
    mem = LocalMemory("t", embedder=HashEmbedder())
    mem.add("a", 1, "morning", "observation", "Had tea at the café with a friend", 2)
    mem.add("a", 2, "evening", "observation", "Missed the scooter EMI; credit score dropped", 9)
    mem.add("a", 9, "morning", "observation", "Watered the plants", 1)
    top = mem.retrieve("a", "loan EMI payment due", now_day=10, k=1)
    assert "EMI" in top[0].text
    assert mem.retrieve("b", "anything", now_day=10) == []


# ── LLM pool ────────────────────────────────────────────────────────────────

def test_extract_json_tolerates_chatter_and_fences():
    assert extract_json('Sure! ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('thinking... {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    assert extract_json("no json here") is None


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


def test_pool_falls_back_when_a_provider_is_rate_limited():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.host)
        if req.url.host == "first.test":
            return httpx.Response(429, headers={"retry-after": "30"}, json={"error": "slow down"})
        return _completion('{"ok": true}')

    provs = [Provider("first", "https://first.test/v1", "k1", "m", 30, 100000, True, label="first"),
             Provider("second", "https://second.test/v1", "k2", "m", 30, 100000, True, label="second")]
    pool = LLMPool(provs, transport=httpx.MockTransport(handler))
    data, used = run(pool.chat_json("sys", "user"))
    assert data == {"ok": True} and used == "second"
    assert calls == ["first.test", "second.test"]
    assert provs[0].failures == 1 and provs[1].calls == 1


def test_pool_raises_when_nobody_answers():
    pool = LLMPool([Provider("x", "https://x.test/v1", "k", "m", 30, 100000, True, label="x")],
                   transport=httpx.MockTransport(lambda r: httpx.Response(500, text="down")))
    with pytest.raises(LLMUnavailable):
        run(pool.chat_json("sys", "user", max_attempts=2))


def test_normalise_decision_repairs_bad_fields():
    pop = generate_population(20, seed=7)
    agents = {a.id: a for a in pop}
    a = pop[0]
    raw = {"thought": "ok", "morning": {"place": "Town Mall & Cinema", "do": "Leisure", "spend": "300"},
           "afternoon": {"place": "the moon", "do": "fly"}, "evening": "nonsense",
           "money": {"borrow_moneylender": "2000", "skip": "rent"}, "talk_to": pop[1].name}
    plan, fixes = normalise_decision(raw, a, agents)
    assert plan["morning"] == {"place": "mall", "do": "leisure", "spend": 300}
    assert plan["afternoon"]["place"] == a.home and fixes
    assert plan["money"]["borrow_moneylender"] == 2000 and plan["money"]["skip"] == ["rent"]
    assert plan["talk_to"] == pop[1].id


def test_spending_at_the_bank_means_repaying():
    pop = generate_population(20, seed=7)
    agents = {a.id: a for a in pop}
    a = pop[0]
    raw = {"thought": "pay the loan", "morning": {"place": "bank", "do": "bank", "spend": 600},
           "afternoon": {"place": a.home, "do": "rest", "spend": 50}, "evening": {"place": a.home, "do": "rest"}}
    plan, _ = normalise_decision(raw, a, agents)
    assert plan["morning"]["spend"] == 0 and plan["money"]["repay_extra"] == 600
    assert plan["afternoon"]["spend"] == 0


# ── the full loop with a fake LLM ───────────────────────────────────────────

class FakeLLM:
    """Answers like a provider would, based on what the prompt asks for."""

    def __init__(self):
        self.prompts = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        user = body["messages"][-1]["content"]
        system = body["messages"][0]["content"]
        self.prompts.append(user)
        if "conversation" in system:
            ids = re.findall(r'"speaker": "(a\d\d)"', user)
            a, b = ids[0], ids[1]
            # whatever the first speaker read in the news, they pass on
            heard = re.search(r"Read in the news: ([^\n]+)", user)
            news = heard.group(1) if heard else "prices are going up"
            return _completion(json.dumps({
                "dialogue": [{"speaker": a, "text": f"Did you hear? {news}"},
                             {"speaker": b, "text": "No! I should buy groceries before they cost more."}],
                f"{a}_learned": "My neighbour is worried too.", f"{b}_learned": f"Heard that {news}",
                f"{a}_importance": 4, f"{b}_importance": 7}))
        if "insights" in user:
            return _completion('{"insights": ["Prices keep rising, so I will buy in bulk and skip eating out."]}')
        home = re.search(r"your home is (\w+)", user).group(1)
        work = re.search(r"Work: (\w+) \(", user)
        known = re.search(r"People you know: (a\d\d)", user)
        place = work.group(1) if work else home
        return _completion(json.dumps({
            "thought": "Prices are rising, so I'll work and stock up on groceries.",
            "morning": {"place": place, "do": "work", "spend": 0},
            "afternoon": {"place": place, "do": "work", "spend": 0},
            "evening": {"place": "park", "do": "socialise", "spend": 0},
            "money": {"borrow_bank": 0, "borrow_moneylender": 0, "repay_extra": 0, "send_home": 0, "skip": []},
            "talk_to": known.group(1) if known else "", "talk_about": "rising prices"}))


def _llm_sim(days=4, **kw):
    fake = FakeLLM()
    pool = LLMPool([Provider("fake", "https://fake.test/v1", "k", "m", 10_000, 10 ** 9, True, label="fake")],
                   transport=httpx.MockTransport(fake))
    sim = TownSimulation(shock=PRESETS["severe"], headlines=["Petrol price jumps by ₹12 a litre"],
                         n_agents=12, seed=5, days=days, brain=LLMBrain(pool),
                         memory=LocalMemory("t", HashEmbedder()), **kw)
    return sim, fake


def _collect(sim):
    async def go():
        return [ev async for ev in sim.run()]
    return run(go())


def test_llm_agents_decide_talk_and_remember():
    sim, fake = _llm_sim(days=4)
    events = _collect(sim)
    kinds = {e["type"] for e in events}
    assert {"run_start", "day_start", "decision", "move", "conversation", "day_end", "run_end"} <= kinds
    llm_decisions = [e for e in events if e["type"] == "decision" and e["mode"] == "llm"]
    assert len(llm_decisions) >= 12 and all(e["provider"] == "fake" for e in llm_decisions)
    # agents read their own memories back when deciding
    assert any("WHAT YOU REMEMBER" in p and "steady for months" in p for p in fake.prompts)
    convs = [e for e in events if e["type"] == "conversation"]
    assert convs and all(len(c["dialogue"]) >= 2 for c in convs)
    a, b = convs[0]["a"], convs[0]["b"]
    assert any(m.kind == "conversation" for m in sim.memory.all(b))
    # the run summary reports usage
    assert events[-1]["type"] == "run_end" and events[-1]["usage"][0]["calls"] > 0


def test_news_spreads_to_agents_who_do_not_read_it():
    sim, _ = _llm_sim(days=5)
    _collect(sim)
    non_readers = [a for a in sim.agents.values() if not a.reads_news]
    assert non_readers, "seed should include people who don't follow the news"
    heard = [a for a in non_readers if any("Petrol price jumps" in m.text for m in sim.memory.all(a.id))]
    assert heard, "a non-reader should hear the headline from someone in conversation"


def test_agents_fall_back_to_routine_when_llm_is_down():
    pool = LLMPool([Provider("x", "https://x.test/v1", "k", "m", 10_000, 10 ** 9, True, label="x")],
                   transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")))
    sim = TownSimulation(shock=PRESETS["mild"], n_agents=6, seed=2, days=2, brain=LLMBrain(pool),
                         memory=LocalMemory("t", HashEmbedder()))
    events = _collect(sim)
    modes = {e["mode"] for e in events if e["type"] == "decision"}
    assert modes <= {"fallback", "routine"} and sim.stats["fallbacks"] > 0


def test_mock_month_keeps_the_books_consistent():
    sim = TownSimulation(shock=PRESETS["severe"], n_agents=20, seed=7, days=30,
                         memory=LocalMemory("t", HashEmbedder()))
    events = _collect(sim)
    ends = [e for e in events if e["type"] == "day_end"]
    assert len(ends) == 30
    for e in ends:
        for snap in e["agents"].values():
            assert snap["money"] >= 0
            assert 0 <= snap["pantry_days"] <= 30
    assert ends[-1]["town"]["prices"]["groceries"] == pytest.approx(1.45)
    assert all(e["mode"] in ("mock", "routine") for e in events if e["type"] == "decision")


def test_rate_budget_is_respected():
    p = Provider("x", "https://x.test/v1", "k", "m", rpm=2, tpm=1000, json_mode=True, label="x")
    p.reserve(100, now=0.0)
    p.reserve(100, now=1.0)
    assert p.wait_needed(100, now=2.0) > 55          # third request this minute must wait
    assert p.wait_needed(100, now=61.0) == 0
    q = Provider("y", "https://y.test/v1", "k", "m", rpm=100, tpm=1000, json_mode=True, label="y")
    q.reserve(900, now=0.0)
    assert q.wait_needed(200, now=1.0) > 55          # token budget, not request count


def test_fast_pace_brings_the_shock_forward():
    from town.engine import PACES
    onset, ramp = PACES["fast"]
    econ = TownEconomy(PRESETS["severe"], seed=1, onset_day=onset, ramp_days=ramp,
                       headlines=["a", "b", "c"])
    assert econ.ramp(1) == 0 and econ.ramp(2) > 0 and econ.ramp(5) == 1.0
    assert econ.layoff_day == 5
    assert sorted(econ.news) == [2, 3, 4]            # headlines arrive daily in a short run
    normal = TownEconomy(PRESETS["severe"], seed=1)
    assert normal.ramp(2) == 0 and normal.ramp(10) == 1.0 and normal.layoff_day == 10

