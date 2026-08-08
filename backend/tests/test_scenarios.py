import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_parse_scenario_ambiguous():
    response = client.post(
        "/scenarios/parse",
        json={"description": "fuel prices go up"}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert "understood" in data
    assert "ambiguous_or_missing" in data
    
    # Verify that ambiguous_or_missing has at least one entry
    assert len(data["ambiguous_or_missing"]) >= 1
    
    # We can also check if the fallback response is returned when GROQ_API_KEY is not set
    # but the assertion `len(...) >= 1` covers both the fallback mock and a real ambiguous LLM response.
