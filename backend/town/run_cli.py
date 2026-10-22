"""
Run the town headlessly and print what happens.

  python -m town.run_cli --preset severe --days 10              # real agents if keys are set, else mock
  python -m town.run_cli --brain mock --days 30 --agents 20
  python -m town.run_cli --scenario 74                           # use a scenario's mapped shock from the DB
  python -m town.run_cli --preset severe --days 7 --pace fast    # shock hits from day 2 (short demo runs)

The full event log is written to runs/<run_id>.jsonl (replayable later).
"""

import argparse
import asyncio
import json
import os
import time

from simulation.shock import describe
from town.scenarios import SCENARIOS
from town.engine import TownSimulation, make_brain
from town.llm_pool import load_env
from town.memory import make_memory

def scenario_from_db(scenario_id: int):
    from simulation.shock import shock_from_deltas
    from db.session import SessionLocal
    from models.scenarios import Scenario
    nodes = _ensure_mapped_chain_for(scenario_id)
    db = SessionLocal()
    try:
        sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        title = sc.name if sc else f"Scenario {scenario_id}"
    finally:
        db.close()
    heads = [title] + [n.get("description", "") for n in nodes[:7]]
    return shock_from_deltas(nodes), heads, title


def _ensure_mapped_chain_for(scenario_id: int):
    from db.session import SessionLocal
    from models.causal_chains import CausalChain
    from app.api.endpoints.simulate import _ensure_mapped_chain
    db = SessionLocal()
    try:
        rec = (db.query(CausalChain).filter(CausalChain.scenario_id == scenario_id)
               .order_by(CausalChain.id.desc()).first())
    finally:
        db.close()
    if rec is None:
        raise SystemExit(f"Scenario {scenario_id} has no causal chain")
    return _ensure_mapped_chain(rec.id)


def fmt(ev, names):
    t = ev["type"]
    n = lambda aid: names.get(aid, aid)
    if t == "day_start":
        news = ("  NEWS: " + " | ".join(ev["news"])) if ev["news"] else ""
        return f"\n══ Day {ev['day']} ({ev['weekday']})  groceries x{ev['prices']['groceries']:.2f}  petrol ₹{ev['fuel_price']:.0f}{news}"
    if t == "decision":
        if ev["mode"] == "routine":
            return None
        p = ev["plan"]
        route = " → ".join(f"{p[ph]['place']}:{p[ph]['do']}" + (f" ₹{p[ph]['spend']:.0f}" if p[ph]['spend'] else "")
                           for ph in ("morning", "afternoon", "evening"))
        return f"  [{ev['mode']:<7}] {n(ev['agent']):<18} “{ev['thought'][:140]}”\n{'':13}{route}"
    if t == "action" and (ev["importance"] >= 6 or not ev["ok"]):
        return f"     • {n(ev['agent'])}: {ev['text']}"
    if t == "conversation":
        lines = "\n".join(f"        {n(l.get('speaker'))}: {l.get('text', '')[:120]}" for l in ev["dialogue"][:4])
        return f"   💬 {n(ev['a'])} & {n(ev['b'])} at {ev['place']} ({ev['phase']}):\n{lines}"
    if t == "reflection":
        return f"   🧠 {n(ev['agent'])} concludes: " + " / ".join(ev["insights"])
    if t == "day_end":
        s = ev["town"]
        return (f"  — avg money ₹{s['avg_money']:,.0f} | low on food {s['low_food']} | hungry {s['hungry_today']} | "
                f"defaulted {s['defaulted']} | jobless {s['unemployed']} | moneylender {s['moneylender_borrowers']}")
    return None


async def main(args):
    rules = None
    if args.scenario:
        shock, heads, title = scenario_from_db(args.scenario)
    else:
        sc = SCENARIOS[args.preset]
        shock, heads, title, rules = sc.shock, list(sc.headlines), f"preset: {args.preset}", sc.rules
    brain = make_brain(args.brain)
    sim = TownSimulation(shock=shock, headlines=heads, n_agents=args.agents, seed=args.seed, days=args.days,
                         brain=brain, memory=make_memory("cli", prefer=args.memory), title=title,
                         pace=args.pace, rules=rules)
    sim.memory.run_id = sim.run_id
    os.makedirs("runs", exist_ok=True)
    path = os.path.join("runs", f"{sim.run_id}.jsonl")
    names = {aid: a.name for aid, a in sim.agents.items()}
    print(f"Run {sim.run_id}: {title}; shock: {describe(shock)}")
    print(f"Brain: {brain.kind}" + (f" via {brain.pool.describe()}" if hasattr(brain, 'pool') else "")
          + f"; memory: {sim.memory.backend}")
    t0 = time.time()
    with open(path, "w") as f:
        async for ev in sim.run():
            f.write(json.dumps(ev, default=str) + "\n")
            line = fmt(ev, names)
            if line and not args.quiet:
                print(line, flush=True)
    print(f"\nDone in {time.time() - t0:.0f}s. Stats: {sim.stats}")
    if hasattr(brain, "pool"):
        for u in brain.pool.usage():
            print(f"  {u['provider']}: {u['calls']} calls, {u['prompt_tokens'] + u['completion_tokens']:,} tokens, "
                  f"{u['failures']} failures")
        await brain.pool.close()
    print(f"Event log: {path}")


if __name__ == "__main__":
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list(SCENARIOS), default="severe")
    ap.add_argument("--scenario", type=int, default=None)
    ap.add_argument("--brain", choices=("auto", "llm", "mock"), default="auto")
    ap.add_argument("--memory", choices=("auto", "local", "qdrant"), default="auto")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--pace", choices=("normal", "fast"), default="normal",
                    help="fast: shock starts on day 2 and is at full strength by day 5 (for short runs)")
    ap.add_argument("--agents", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quiet", action="store_true")
    asyncio.run(main(ap.parse_args()))
