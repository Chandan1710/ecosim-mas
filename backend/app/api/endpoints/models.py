from pydantic import BaseModel, Field
from typing import List, Optional

# ── Scenario Parser models (module 2) ────────────────────────────────────────

class ScenarioParseRequest(BaseModel):
    description: str
    date_override: Optional[str] = None
    location_override: Optional[str] = None


class AmbiguousQuestion(BaseModel):
    field: str
    question: str


class ScenarioParseResponse(BaseModel):
    understood: List[str]
    region: Optional[str] = None
    time_horizon_months: Optional[int] = None
    primary_event: str
    affected_sectors: List[str]
    ambiguous_or_missing: List[AmbiguousQuestion]


# ── Causal Chain models (module 3) ────────────────────────────────────────────

class CausalChainRequest(BaseModel):
    """Input to POST /scenarios/{scenario_id}/causal-chain.

    Pass the ScenarioParseResponse fields directly so the engine has the
    primary_event, region, affected_sectors, and time horizon to reason over.
    """
    primary_event: str
    region: Optional[str] = None
    time_horizon_months: Optional[int] = None
    affected_sectors: List[str] = Field(default_factory=list)
    date_override: Optional[str] = None
    location_override: Optional[str] = None


class CausalNode(BaseModel):
    node_id: int
    description: str
    magnitude: str                    # "major" | "moderate" | "minor"
    category: str                     # "prices" | "employment" | ...
    depends_on: List[int]             # [] for node_id 1
    confidence: float                 # 0.0 – 1.0


class CausalChainResponse(BaseModel):
    scenario_id: int
    chain_id: int
    chain: List[CausalNode] = Field(..., min_length=10, max_length=15)
