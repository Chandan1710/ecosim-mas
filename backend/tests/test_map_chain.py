"""Tests for the Semantic-to-Numerical Mapper (module 6).

Strategy
--------
* Seed a real Scenario + CausalChain row so the FK chain is satisfied.
* Mock `map_node_to_deltas` in llm.py to return a deterministic,
  directionally-sensible delta for a rate-hike node — keeps the test
  fast and independent of API keys, while still exercising the full
  endpoint + response-shape path.
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain

client = TestClient(app)


def _seed_scenario_with_chain(db) -> tuple[int, int]:
    scenario = Scenario(name="RBI repo rate hike 50bps", description="Test scenario")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    chain = CausalChain(
        scenario_id=scenario.id,
        chain=[
            {
                "node_id": 1,
                "description": "RBI raises the repo rate by 50 basis points, tightening credit conditions.",
                "magnitude": "major",
                "category": "credit",
                "depends_on": [],
                "confidence": 0.95,
            }
        ],
    )
    db.add(chain)
    db.commit()
    db.refresh(chain)
    return scenario.id, chain.id


def test_map_chain_directionally_sensible():
    """
    Mapping a rate-hike node should produce a NEGATIVE credit_availability_pct
    (credit tightens) and all four required delta fields present.
    """
    db = SessionLocal()
    try:
        scenario_id, chain_id = _seed_scenario_with_chain(db)
    finally:
        db.close()

    mock_delta = {
        "node_id": 1,
        "deltas": {
            "discretionary_spend_pct": -0.08,
            "savings_rate_pct": 0.05,
            "essential_cost_index_pct": 0.02,
            "credit_availability_pct": -0.15,
        },
        "rationale": "Higher repo rate raises borrowing costs, tightening credit availability.",
    }

    with patch("app.api.endpoints.map.map_node_to_deltas", return_value=mock_delta):
        response = client.post(f"/scenarios/{scenario_id}/causal-chain/map")

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["scenario_id"] == scenario_id
    assert data["chain_id"] == chain_id
    assert len(data["mapped_nodes"]) == 1

    node_result = data["mapped_nodes"][0]
    deltas = node_result["deltas"]

    # All four required fields present
    for field in (
        "discretionary_spend_pct",
        "savings_rate_pct",
        "essential_cost_index_pct",
        "credit_availability_pct",
    ):
        assert field in deltas
        assert -1.0 <= deltas[field] <= 1.0, f"{field} out of range: {deltas[field]}"

    # Directionally sensible: a rate hike should tighten credit
    assert deltas["credit_availability_pct"] < 0, (
        "A repo rate hike should produce a negative credit_availability_pct"
    )


def test_map_chain_404_for_missing_scenario():
    response = client.post("/scenarios/999999/causal-chain/map")
    assert response.status_code == 404


def test_map_chain_404_when_no_chain_exists():
    db = SessionLocal()
    try:
        scenario = Scenario(name="No chain yet", description="Test")
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        scenario_id = scenario.id
    finally:
        db.close()

    response = client.post(f"/scenarios/{scenario_id}/causal-chain/map")
    assert response.status_code == 404
