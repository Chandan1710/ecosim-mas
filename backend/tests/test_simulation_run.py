"""
Tests for Module 9: Live Simulation Streaming.

Strategy
--------
* Seed a real Scenario and CausalChain row (as in test_causal_chains.py).
* Mock `personas_from_db` to use the fixture JSON so the test works without
  a seeded personas table.
* Mock `predict_risk_score` to avoid needing a trained model file.
* Mock `store_episode` to avoid needing a live Qdrant instance.
* Start the simulation via POST, then connect the WebSocket and collect
  at least 3 tick messages, asserting the expected shape.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain
from simulation.env_factory import personas_from_fixtures
from simulation.ecosim_env import AgentPersona

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

PERSONAS_FIXTURE = [
    {"name": "Frugal Senior",       "risk_appetite": 0.1, "financial_literacy": 0.8, "spending_bias": 0.2},
    {"name": "Aggressive Student",  "risk_appetite": 0.9, "financial_literacy": 0.3, "spending_bias": 0.8},
    {"name": "Cautious Professional","risk_appetite": 0.4, "financial_literacy": 0.9, "spending_bias": 0.5},
    {"name": "Impulse Spender",     "risk_appetite": 0.3, "financial_literacy": 0.4, "spending_bias": 0.9},
    {"name": "Debt Avoider",        "risk_appetite": 0.2, "financial_literacy": 0.7, "spending_bias": 0.3},
    {"name": "Gig Worker",          "risk_appetite": 0.6, "financial_literacy": 0.5, "spending_bias": 0.6},
    {"name": "Rural Farmer",        "risk_appetite": 0.5, "financial_literacy": 0.3, "spending_bias": 0.4},
    {"name": "Urban Middle Class",  "risk_appetite": 0.5, "financial_literacy": 0.6, "spending_bias": 0.5},
    {"name": "Retiree",             "risk_appetite": 0.2, "financial_literacy": 0.7, "spending_bias": 0.3},
    {"name": "Young Professional",  "risk_appetite": 0.7, "financial_literacy": 0.8, "spending_bias": 0.6},
]

MOCK_CHAIN = [
    {
        "node_id":     i,
        "description": f"Consequence {i} of the repo rate hike.",
        "magnitude":   "major" if i <= 3 else ("moderate" if i <= 8 else "minor"),
        "category":    "credit",
        "depends_on":  [] if i == 1 else [i - 1],
        "confidence":  round(1.0 - (i - 1) * 0.05, 2),
    }
    for i in range(1, 13)
]



def _seed_scenario_and_chain(db) -> tuple[int, int]:
    """Insert a Scenario and CausalChain row, return (scenario_id, chain_id)."""
    scenario = Scenario(name="RBI rate hike — sim test", description="Module 9 test")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    chain = CausalChain(scenario_id=scenario.id, chain=MOCK_CHAIN)
    db.add(chain)
    db.commit()
    db.refresh(chain)

    return scenario.id, chain.id


def _save_only_space():
    """
    Return a mock action space whose .sample() always returns SAVE (1) with
    magnitude 0.5. Prevents random DEFAULT actions from terminating all agents
    before we can collect 3 tick messages in the streaming test.
    """
    import numpy as np
    space = MagicMock()
    space.sample.return_value = (1, np.array([0.5], dtype=np.float32))  # (SAVE, 0.5)
    return space



# ── Tests ─────────────────────────────────────────────────────────────────────

def test_simulation_run_streams_ticks():
    """
    End-to-end test:
      1. Seed scenario + causal chain.
      2. POST /scenarios/{id}/simulate/start → get run_id.
      3. Connect WebSocket /ws/simulate/{run_id}.
      4. Assert at least 3 tick messages arrive with the correct shape.
    """
    db = SessionLocal()
    try:
        scenario_id, chain_id = _seed_scenario_and_chain(db)
    finally:
        db.close()

    with (
        # Avoid DB lookup for personas — use fixture data instead
        patch(
            "app.api.endpoints.simulate.personas_from_db",
            return_value=personas_from_fixtures(PERSONAS_FIXTURE),
        ),
        # Avoid needing a trained model file
        patch(
            "app.api.endpoints.simulate.predict_risk_score",
            return_value=0.42,
        ),
        # Avoid needing a live Qdrant instance
        patch(
            "app.api.endpoints.simulate.store_episode",
            return_value=None,
        ),
    ):
        # ── Step 1: Start the run ─────────────────────────────────────────────
        start_resp = client.post(f"/scenarios/{scenario_id}/simulate/start")
        assert start_resp.status_code == 200, start_resp.text

        start_data = start_resp.json()
        assert "run_id" in start_data
        run_id = start_data["run_id"]

        # ── Step 2: Connect WebSocket and collect messages ────────────────────
        tick_messages = []
        with client.websocket_connect(f"/ws/simulate/{run_id}") as ws:
            for _ in range(50):   # safety cap — we'll break early
                msg = ws.receive_json()

                if msg.get("status") == "simulation_complete":
                    break

                if "error" in msg:
                    raise AssertionError(f"Simulation returned an error: {msg['error']}")

                tick_messages.append(msg)

                # Stop reading after 3 good ticks — we don't need to run the whole episode
                if len(tick_messages) >= 3:
                    break

    # ── Assertions ────────────────────────────────────────────────────────────
    assert len(tick_messages) >= 3, (
        f"Expected at least 3 tick messages, got {len(tick_messages)}"
    )

    for i, msg in enumerate(tick_messages):
        # Required top-level keys
        assert "tick" in msg,          f"tick {i}: missing 'tick'"
        assert "agent_actions" in msg, f"tick {i}: missing 'agent_actions'"
        assert "macro_state" in msg,   f"tick {i}: missing 'macro_state'"
        assert "risk_score" in msg,    f"tick {i}: missing 'risk_score'"
        assert "active_agents" in msg, f"tick {i}: missing 'active_agents'"

        # macro_state has the three expected keys
        macro = msg["macro_state"]
        assert "inflation_rate"    in macro, f"tick {i}: missing inflation_rate"
        assert "repo_rate"         in macro, f"tick {i}: missing repo_rate"
        assert "fuel_price_index"  in macro, f"tick {i}: missing fuel_price_index"

        # risk_score is a valid float (mocked to 0.42 here)
        assert isinstance(msg["risk_score"], float), f"tick {i}: risk_score not a float"

        # Every agent action has the three expected sub-keys
        for agent_id, action_data in msg["agent_actions"].items():
            assert "action_type" in action_data, f"tick {i} agent {agent_id}: missing action_type"
            assert "magnitude"   in action_data, f"tick {i} agent {agent_id}: missing magnitude"
            assert "reward"      in action_data, f"tick {i} agent {agent_id}: missing reward"

        # tick counter is non-negative
        assert msg["tick"] >= 0, f"tick {i}: negative tick counter"


def test_simulation_start_returns_run_id():
    """Smoke test: the start endpoint returns a UUID run_id."""
    db = SessionLocal()
    try:
        scenario_id, _ = _seed_scenario_and_chain(db)
    finally:
        db.close()

    with (
        patch(
            "app.api.endpoints.simulate.personas_from_db",
            return_value=personas_from_fixtures(PERSONAS_FIXTURE),
        ),
        patch("app.api.endpoints.simulate.predict_risk_score", return_value=0.5),
        patch("app.api.endpoints.simulate.store_episode", return_value=None),
    ):
        resp = client.post(f"/scenarios/{scenario_id}/simulate/start")

    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "scenario_id" in data
    assert data["scenario_id"] == scenario_id
    # UUID format check (basic)
    import uuid
    uuid.UUID(data["run_id"])   # raises ValueError if malformed


def test_simulation_start_404_for_missing_scenario():
    """Returns 404 when the scenario doesn't exist."""
    resp = client.post("/scenarios/999999/simulate/start")
    assert resp.status_code == 404


def test_simulation_start_404_for_missing_chain():
    """Returns 404 when the scenario exists but has no causal chain."""
    db = SessionLocal()
    try:
        scenario = Scenario(name="No-chain scenario", description="")
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        scenario_id = scenario.id
    finally:
        db.close()

    with patch(
        "app.api.endpoints.simulate.personas_from_db",
        return_value=personas_from_fixtures(PERSONAS_FIXTURE),
    ):
        resp = client.post(f"/scenarios/{scenario_id}/simulate/start")

    assert resp.status_code == 404


def test_websocket_returns_404_for_unknown_run():
    """WebSocket closes immediately with code 4404 for an unknown run_id."""
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/simulate/nonexistent-run-id"):
            pass   # server should reject before we send/receive anything
    assert exc_info.value.code == 4404
