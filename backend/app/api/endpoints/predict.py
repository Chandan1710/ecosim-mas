"""
POST /predict/risk-score

Exposes the trained LightGBM ML model for inference.
Takes a macro_state and agent_state snapshot, returns the predicted risk_score.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any

from ml.predict import predict_risk_score

router = APIRouter()

class RiskPredictionRequest(BaseModel):
    macro_state: Dict[str, Any]
    agent_state: Dict[str, Any]

class RiskPredictionResponse(BaseModel):
    risk_score: float

@router.post("/risk-score", response_model=RiskPredictionResponse)
def get_risk_score(request: RiskPredictionRequest):
    """
    Predicts the risk score using the LightGBM model.
    """
    score = predict_risk_score(request.macro_state, request.agent_state)
    return RiskPredictionResponse(risk_score=score)
