"""
Tests for Module 8: ML Prediction Layer
"""

import pytest
import os
import joblib
from fastapi.testclient import TestClient

from app.main import app
from ml.train_lightgbm import train_model, MODEL_PATH

client = TestClient(app)

def test_ml_pipeline():
    """
    End-to-end test for the ML prediction layer:
    1. Triggers training on the synthetic fixture.
    2. Verifies the LightGBM model is saved to disk.
    3. Calls the prediction endpoint via FastAPI and checks the output bounds.
    """
    # 1. Train the model
    train_model()
    
    # 2. Verify model persistence
    assert os.path.exists(MODEL_PATH), "Model was not saved to expected path"
    
    # 3. Call prediction endpoint
    payload = {
        "macro_state": {
            "inflation_rate": 6.5, 
            "repo_rate": 6.0, 
            "fuel_price_index": 120.0
        },
        "agent_state": {
            "budget_anxiety": 0.8, 
            "essential_pressure": 0.9, 
            "liquidity": 0.1
        }
    }
    
    response = client.post("/predict/risk-score", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "risk_score" in data
    
    score = data["risk_score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0, f"Predicted score {score} is out of bounds [0.0, 1.0]"
