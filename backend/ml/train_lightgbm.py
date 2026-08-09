"""
Module 8: ML Prediction Layer - LightGBM Training

Trains a LightGBM regressor to predict `risk_score` from macro and agent states.
Uses the synthetic simulation logs fixture.
"""

import json
import os
import lightgbm as lgb
import numpy as np
import joblib

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "synthetic_simulation_logs.json")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "lightgbm_risk.pkl")

# Define the expected feature order (important for inference matching)
FEATURE_COLS = [
    "inflation_rate", 
    "repo_rate", 
    "fuel_price_index", 
    "budget_anxiety", 
    "essential_pressure", 
    "liquidity"
]

def extract_features(record: dict) -> list:
    macro = record.get("macro_state", {})
    agent = record.get("agent_state", {})
    return [
        macro.get("inflation_rate", 0.0),
        macro.get("repo_rate", 0.0),
        macro.get("fuel_price_index", 0.0),
        agent.get("budget_anxiety", 0.0),
        agent.get("essential_pressure", 0.0),
        agent.get("liquidity", 0.0)
    ]

def train_model():
    print(f"Loading synthetic logs from {FIXTURE_PATH}")
    with open(FIXTURE_PATH, "r") as f:
        records = json.load(f)
    
    X = []
    y = []
    
    for record in records:
        X.append(extract_features(record))
        y.append(record.get("risk_score", 0.0))
        
    X = np.array(X)
    y = np.array(y)
    
    print(f"Training LightGBM on {len(X)} samples with {len(FEATURE_COLS)} features...")
    
    # We use a small number of estimators for this synthetic set
    model = lgb.LGBMRegressor(
        n_estimators=50, 
        learning_rate=0.05, 
        random_state=42, 
        max_depth=3,
        verbosity=-1
    )
    
    model.fit(X, y)
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    # We save both the model and the feature column list so predict.py knows the exact ordering
    payload = {
        "model": model,
        "features": FEATURE_COLS
    }
    
    joblib.dump(payload, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")

if __name__ == "__main__":
    train_model()
