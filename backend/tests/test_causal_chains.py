"""Tests for the Causal Chain Engine (module 3).

Strategy
--------
* We seed a real Scenario row so the FK constraint is satisfied.
* We mock `generate_causal_chain` in llm.py to return a deterministic
  12-node chain — this keeps the test fast and independent of API keys /
  network, while still exercising the full endpoint + persistence path.
* A second test verifies the Ollama fallback fires when Groq raises
  APITimeoutError, mirroring the pattern from test_scenarios.py.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain

client = TestClient(app)

VALID_MAGNITUDES = {"major", "moderate", "minor"}

def _make_chain(n: int = 12) -> list[dict]:
    """Return a syntactically valid n-node chain."""
    return [
        {
            "node_id": i,
            "description": f"Consequence {i} of the repo rate hike.",
            "magnitude": "major" if i <= 3 else ("moderate" if i <= 8 else "minor"),
            "category": "credit",
            "depends_on": [] if i == 1 else [i - 1],
            "confidence": round(1.0 - (i - 1) * 0.05, 2),
        }
        for i in range(1, n + 1)
    ]


def _seed_scenario(db) -> Scenario:
    s = Scenario(name="RBI repo rate hike 50bps", description="Test scenario")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_causal_chain_structure():
    """
    Submit a realistic scenario and assert:
    - Response has 10-15 nodes.
    - node_id 1 has an empty depends_on list.
    - Every node has a valid magnitude.
    """
    db = SessionLocal()
    try:
        scenario = _seed_scenario(db)
        scenario_id = scenario.id
    finally:
        db.close()

    mock_chain = _make_chain(12)

    with patch("app.api.endpoints.causal_chains.generate_causal_chain", return_value=mock_chain):
        response = client.post(
            f"/scenarios/{scenario_id}/causal-chain",
            json={
                "primary_event": "RBI raises the repo rate by 50 basis points.",
                "region": "India",
                "time_horizon_months": 6,
                "affected_sectors": ["credit", "consumer_behaviour", "employment"],
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()

    chain = data["chain"]

    # 10-15 node constraint
    assert 10 <= len(chain) <= 15, f"Chain length {len(chain)} is out of [10, 15]"

    # node_id 1 must have empty depends_on
    node_1 = next(n for n in chain if n["node_id"] == 1)
    assert node_1["depends_on"] == [], "node_id 1 must have depends_on == []"

    # every node has a valid magnitude
    for node in chain:
        assert node["magnitude"] in VALID_MAGNITUDES, (
            f"node_id {node['node_id']} has invalid magnitude '{node['magnitude']}'"
        )


def test_causal_chain_persisted():
    """Chain should be retrievable from the DB after the endpoint call."""
    db = SessionLocal()
    try:
        scenario = _seed_scenario(db)
        scenario_id = scenario.id
    finally:
        db.close()

    mock_chain = _make_chain(10)

    with patch("app.api.endpoints.causal_chains.generate_causal_chain", return_value=mock_chain):
        response = client.post(
            f"/scenarios/{scenario_id}/causal-chain",
            json={"primary_event": "RBI raises the repo rate by 50 basis points."},
        )

    assert response.status_code == 200
    chain_id = response.json()["chain_id"]

    db = SessionLocal()
    try:
        record = db.query(CausalChain).filter(CausalChain.id == chain_id).first()
        assert record is not None, "CausalChain record not found in DB"
        assert record.scenario_id == scenario_id
        assert len(record.chain) == 10
    finally:
        db.close()


def test_causal_chain_ollama_fallback_on_groq_timeout():
    """When Groq times out, the endpoint should fall through to Ollama and still return a valid chain."""
    from groq import APITimeoutError

    db = SessionLocal()
    try:
        scenario = _seed_scenario(db)
        scenario_id = scenario.id
    finally:
        db.close()

    mock_chain = _make_chain(11)
    groq_timeout = APITimeoutError(request=MagicMock())

    with patch("app.services.llm.Groq") as MockGroq, \
         patch("app.services.llm._call_ollama_chain", return_value=mock_chain) as mock_ollama, \
         patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

        mock_client = MagicMock()
        MockGroq.return_value = mock_client
        mock_client.chat.completions.create.side_effect = groq_timeout

        response = client.post(
            f"/scenarios/{scenario_id}/causal-chain",
            json={"primary_event": "RBI raises the repo rate by 50 basis points."},
        )

    assert response.status_code == 200
    data = response.json()
    assert 10 <= len(data["chain"]) <= 15
    mock_ollama.assert_called_once()


def test_causal_chain_404_for_missing_scenario():
    """Should return 404 when scenario_id does not exist."""
    response = client.post(
        "/scenarios/999999/causal-chain",
        json={"primary_event": "Some event"},
    )
    assert response.status_code == 404
