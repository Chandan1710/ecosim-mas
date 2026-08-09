"""
POST /scenarios/{scenario_id}/causal-chain/map

Loads the persisted causal chain for a scenario (from the causal_chains table,
written by module 3) and runs the Semantic-to-Numerical Mapper over every node.

The resulting deltas are intended to seed EcoSimEnv's macro state
(initial_macro parameter) when module 9 wires a live simulation run together.
This endpoint only produces the deltas — it does not start any simulation.

Design note: if a scenario has multiple saved chains (shouldn't happen in
normal flow, but the FK allows it), we pick the most recently created one.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain
from app.api.endpoints.models import (
    MapChainResponse,
    NodeDeltaResult,
    NodeDeltas,
)
from app.services.llm import map_node_to_deltas

router = APIRouter()


@router.post("/{scenario_id}/causal-chain/map", response_model=MapChainResponse)
def map_causal_chain(
    scenario_id: int,
    inflation_rate: Optional[float] = None,
    repo_rate: Optional[float] = None,
    fuel_price_index: Optional[float] = None,
):
    """
    Map every node of the persisted causal chain to numeric deltas.

    Query params (all optional) allow the caller to pass the current macro
    state so the LLM can calibrate delta magnitudes contextually:
      - inflation_rate    (e.g. 5.5)
      - repo_rate         (e.g. 6.5)
      - fuel_price_index  (e.g. 110.0)

    Returns the full list of per-node NodeDeltaResult objects.
    """
    db = SessionLocal()
    try:
        # 1. Verify scenario exists
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not scenario:
            raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")

        # 2. Load the most recent causal chain for this scenario
        chain_record = (
            db.query(CausalChain)
            .filter(CausalChain.scenario_id == scenario_id)
            .order_by(CausalChain.id.desc())
            .first()
        )
        if not chain_record:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No causal chain found for scenario {scenario_id}. "
                    "Call POST /scenarios/{id}/causal-chain first."
                ),
            )

        # 3. Build macro state dict (None fields are omitted so the LLM gets
        #    only what the caller provided, not placeholder zeros)
        macro_state = {}
        if inflation_rate is not None:
            macro_state["inflation_rate"] = inflation_rate
        if repo_rate is not None:
            macro_state["repo_rate"] = repo_rate
        if fuel_price_index is not None:
            macro_state["fuel_price_index"] = fuel_price_index
        macro_state = macro_state or None  # pass None if caller supplied nothing

        # 4. Map each node — one LLM call per node (Groq → Ollama → mock)
        raw_chain: list = chain_record.chain
        mapped_nodes = []
        for node in raw_chain:
            raw_delta = map_node_to_deltas(node=node, macro_state=macro_state)
            mapped_nodes.append(
                NodeDeltaResult(
                    node_id=raw_delta["node_id"],
                    deltas=NodeDeltas(**raw_delta["deltas"]),
                    rationale=raw_delta["rationale"],
                )
            )

        return MapChainResponse(
            scenario_id=scenario_id,
            chain_id=chain_record.id,
            mapped_nodes=mapped_nodes,
        )
    finally:
        db.close()
