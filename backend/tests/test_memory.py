"""
Tests for Module 7: Qdrant Episodic Memory
"""

import pytest
import uuid
import os
from app.services.memory import store_episode, retrieve_similar_episodes, _get_qdrant_client, COLLECTION_NAME

# We want to use a unique collection or namespace for tests if possible,
# but the easiest way is to use unique agent IDs to avoid colliding with other tests/data.

@pytest.fixture(scope="module")
def qdrant_client():
    client = _get_qdrant_client()
    yield client
    # Optionally clean up test data if needed. But we use unique IDs.

def test_store_and_retrieve_episodes():
    # 1. Stores 3 synthetic episodes for frugal_senior.
    agent_1 = f"frugal_senior_test_{uuid.uuid4().hex[:8]}"
    
    # Store episodes for agent_1
    ep1 = {
        "event": {"type": "inflation_shock", "magnitude": "major"},
        "action": {"type": "save", "amount": 0.2},
        "outcome": {"liquidity": "stable", "stress": "low"}
    }
    ep2 = {
        "event": {"type": "job_loss", "magnitude": "major"},
        "action": {"type": "cut_spending", "amount": 0.5},
        "outcome": {"liquidity": "declining", "stress": "high"}
    }
    ep3 = {
        "event": {"type": "windfall", "magnitude": "moderate"},
        "action": {"type": "save", "amount": 0.8},
        "outcome": {"liquidity": "increasing", "stress": "none"}
    }
    
    store_episode(agent_1, ep1["event"], ep1["action"], ep1["outcome"])
    store_episode(agent_1, ep2["event"], ep2["action"], ep2["outcome"])
    store_episode(agent_1, ep3["event"], ep3["action"], ep3["outcome"])

    # 2. Stores 2 synthetic episodes for aggressive_student.
    agent_2 = f"aggressive_student_test_{uuid.uuid4().hex[:8]}"
    
    ep4 = {
        "event": {"type": "inflation_shock", "magnitude": "major"},
        "action": {"type": "spend", "amount": 0.1},
        "outcome": {"liquidity": "critical", "stress": "very_high"}
    }
    ep5 = {
        "event": {"type": "windfall", "magnitude": "moderate"},
        "action": {"type": "invest", "amount": 0.9},
        "outcome": {"liquidity": "low", "stress": "low"}
    }

    store_episode(agent_2, ep4["event"], ep4["action"], ep4["outcome"])
    store_episode(agent_2, ep5["event"], ep5["action"], ep5["outcome"])

    # 3. Queries retrieve_similar_episodes for frugal_senior with a 4th synthetic situation.
    current_situation = {"type": "inflation_shock", "magnitude": "major"}
    
    # Wait briefly if Qdrant needs to index, although it's usually near-instant
    import time
    time.sleep(1)

    results = retrieve_similar_episodes(agent_1, current_situation, k=5)
    
    # 4. Asserts that only frugal_senior episodes are returned, the limit k is respected,
    # and results are ordered by similarity score.
    
    # Check filtering works (only agent_1 returned, so max 3 results)
    assert len(results) == 3, f"Expected 3 results for {agent_1}, got {len(results)}"
    
    # Check ordering (score should be descending)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), "Scores are not descending"
    
    # Check that the most similar episode is ep1 (since the event matches perfectly)
    top_result = results[0]
    assert top_result["event"]["type"] == "inflation_shock"
    assert top_result["action"]["type"] == "save"
    assert top_result["outcome"]["liquidity"] == "stable"
