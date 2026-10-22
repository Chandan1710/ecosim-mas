"""
Create a test scenario (or reuse one) and start a simulation, printing the run_id
to paste into the frontend.

Usage (from backend/, venv active, uvicorn running on :8000):
  python scripts/get_run_id.py            # new scenario: fuel price + inflation shock
  python scripts/get_run_id.py 74         # re-run an existing scenario id

The chain nodes have real descriptions on purpose: simulate/start maps each node
to numeric deltas with the LLM mapper (module 6) and turns them into the run's
shock, so meaningless text like "Consequence" would produce no shock.
"""
import sys

import requests

from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain

CHAIN = [
    ("Fuel prices rise sharply after a global crude oil supply shock.", "major", "energy", []),
    ("Transport and logistics costs increase for businesses.", "major", "supply_chain", [1]),
    ("Food and grocery prices rise as delivery costs are passed on.", "major", "consumer", [2]),
    ("Household essential spending takes a larger share of monthly income.", "moderate", "consumer", [3]),
    ("Consumers cut discretionary spending on dining, travel and shopping.", "moderate", "consumer", [4]),
    ("Banks tighten lending standards as household defaults rise.", "moderate", "credit", [5]),
]


def main():
    if len(sys.argv) > 1:
        scenario_id = int(sys.argv[1])
    else:
        db = SessionLocal()
        try:
            scenario = Scenario(name="Fuel price shock", description="Crude oil supply shock raises fuel and food prices")
            db.add(scenario)
            db.commit()
            db.refresh(scenario)
            scenario_id = scenario.id
            nodes = [
                {"node_id": i, "description": d, "magnitude": m, "category": c,
                 "depends_on": deps, "confidence": round(0.95 - 0.05 * i, 2)}
                for i, (d, m, c, deps) in enumerate(CHAIN, start=1)
            ]
            db.add(CausalChain(scenario_id=scenario_id, chain=nodes))
            db.commit()
        finally:
            db.close()

    resp = requests.post(f"http://localhost:8000/scenarios/{scenario_id}/simulate/start", timeout=120)
    resp.raise_for_status()
    data = resp.json()
    print("scenario_id:", scenario_id)
    print("shock:      ", data.get("shock"))
    print("run_id:     ", data.get("run_id"))


if __name__ == "__main__":
    main()
