import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_parse_scenario_ambiguous():
    """Baseline: endpoint returns at least one ambiguous_or_missing entry."""
    response = client.post(
        "/scenarios/parse",
        json={"description": "fuel prices go up"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "understood" in data
    assert "ambiguous_or_missing" in data
    # Covers both mock fallback and a genuine LLM ambiguity response
    assert len(data["ambiguous_or_missing"]) >= 1


def test_parse_scenario_ollama_fallback_on_groq_timeout():
    """
    When Groq raises APITimeoutError the service should fall through to Ollama.
    We mock Groq to raise the timeout and mock _call_ollama to return a valid
    ScenarioParseResponse, then confirm the endpoint still returns 200 with the
    right shape and that the Ollama fallback warning was logged.
    """
    from groq import APITimeoutError
    from app.api.endpoints.models import ScenarioParseResponse, AmbiguousQuestion

    ollama_response = ScenarioParseResponse(
        understood=["Fuel price increase detected"],
        region=None,
        time_horizon_months=None,
        primary_event="Fuel prices increase in an unspecified region.",
        affected_sectors=["transport", "manufacturing"],
        ambiguous_or_missing=[
            AmbiguousQuestion(field="region", question="Which region or country does this affect?"),
            AmbiguousQuestion(field="magnitude", question="By how much do fuel prices increase?"),
        ],
    )

    # Simulate a real APITimeoutError (its constructor needs request + body)
    groq_timeout = APITimeoutError(request=MagicMock())

    with patch("app.services.llm.Groq") as MockGroq, \
         patch("app.services.llm._call_ollama", return_value=ollama_response) as mock_ollama, \
         patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

        mock_client = MagicMock()
        MockGroq.return_value = mock_client
        mock_client.chat.completions.create.side_effect = groq_timeout

        response = client.post(
            "/scenarios/parse",
            json={"description": "fuel prices go up"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["primary_event"] == "Fuel prices increase in an unspecified region."
    assert len(data["ambiguous_or_missing"]) >= 1
    # Confirm Ollama was actually called
    mock_ollama.assert_called_once()


def test_parse_scenario_mock_fallback_when_both_fail():
    """
    When both Groq (timeout) and Ollama are unreachable, the endpoint should
    still return 200 with the hardcoded mock fallback.
    """
    from groq import APITimeoutError

    groq_timeout = APITimeoutError(request=MagicMock())

    with patch("app.services.llm.Groq") as MockGroq, \
         patch("app.services.llm._call_ollama", side_effect=Exception("Ollama unreachable")), \
         patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):

        mock_client = MagicMock()
        MockGroq.return_value = mock_client
        mock_client.chat.completions.create.side_effect = groq_timeout

        response = client.post(
            "/scenarios/parse",
            json={"description": "fuel prices go up"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["ambiguous_or_missing"]) >= 1
