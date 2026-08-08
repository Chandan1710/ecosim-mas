from fastapi import APIRouter, HTTPException
from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain
from app.api.endpoints.models import (
    CausalChainRequest,
    CausalChainResponse,
    CausalNode,
)
from app.services.llm import generate_causal_chain

router = APIRouter()


@router.post("/{scenario_id}/causal-chain", response_model=CausalChainResponse)
def create_causal_chain(scenario_id: int, request: CausalChainRequest):
    db = SessionLocal()
    try:
        # Verify the scenario exists
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not scenario:
            raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")

        # Generate chain via LLM (Groq → Ollama → mock)
        raw_chain = generate_causal_chain(
            primary_event=request.primary_event,
            region=request.region,
            time_horizon_months=request.time_horizon_months,
            affected_sectors=request.affected_sectors,
            date_override=request.date_override,
            location_override=request.location_override,
        )

        # Persist to causal_chains table
        record = CausalChain(scenario_id=scenario_id, chain=raw_chain)
        db.add(record)
        db.commit()
        db.refresh(record)

        # Build typed response
        nodes = [CausalNode(**node) for node in raw_chain]
        return CausalChainResponse(
            scenario_id=scenario_id,
            chain_id=record.id,
            chain=nodes,
        )
    finally:
        db.close()
