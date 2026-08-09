"""
Module 8: ML Prediction Layer - Predict Service

Loads the trained LightGBM model and provides the `predict_risk_score` function.
"""

import os
import joblib
import numpy as np
import logging

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "lightgbm_risk.pkl")

_model = None
_features = None

def _load_model():
    global _model, _features
    if _model is not None:
        return
    
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Trained model not found at {MODEL_PATH}. Run train_lightgbm.py first.")
    
    try:
        payload = joblib.load(MODEL_PATH)
        _model = payload["model"]
        _features = payload["features"]
        logger.info("Successfully loaded LightGBM risk model.")
    except Exception as e:
        logger.error(f"Failed to load model from {MODEL_PATH}: {e}")
        raise

def predict_risk_score(macro_state: dict, agent_state: dict) -> float:
    """
    Predicts the risk score (0.0 to 1.0) given the macro and agent states.
    """
    _load_model()
    
    # Construct the feature vector strictly in the order the model expects
    x = []
    for f in _features:
        if f in macro_state:
            x.append(float(macro_state[f]))
        elif f in agent_state:
            x.append(float(agent_state[f]))
        else:
            x.append(0.0)  # Default fallback if feature is missing
            
    X = np.array([x])
    
    prediction = _model.predict(X)[0]
    
    # Clip just in case the regressor goes slightly out of bounds
    return float(np.clip(prediction, 0.0, 1.0))
