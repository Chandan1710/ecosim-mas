from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain
import uuid
import sys

def main():
    db = SessionLocal()
    scenario = Scenario(name="Live Test", description="Test")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    scenario_id = scenario.id

    mock_chain = [
        {"node_id": i, "description": "Consequence", "magnitude": "minor", "category": "credit", "depends_on": [], "confidence": 0.8}
        for i in range(1, 4)
    ]
    chain = CausalChain(scenario_id=scenario_id, chain=mock_chain)
    db.add(chain)
    db.commit()
    db.refresh(chain)
    
    db.close()

    import requests
    resp = requests.post(f"http://localhost:8000/scenarios/{scenario_id}/simulate/start")
    print(resp.json())

if __name__ == "__main__":
    main()
