from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.endpoints.models import ScenarioParseRequest, ScenarioParseResponse
from app.services.llm import parse_scenario_with_llm
from db.session import SessionLocal
from models.scenarios import Scenario

router = APIRouter()


class ScenarioCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


class ScenarioCreateResponse(BaseModel):
    scenario_id: int
    name: str


@router.post("/parse", response_model=ScenarioParseResponse)
def parse_scenario(request: ScenarioParseRequest):
    return parse_scenario_with_llm(
        description=request.description,
        date_override=request.date_override,
        location_override=request.location_override
    )


@router.post("", response_model=ScenarioCreateResponse, status_code=201)
def create_scenario(request: ScenarioCreateRequest):
    """
    Create a scenario record. The frontend intake flow calls this once the user
    has confirmed the parsed scenario, then builds the causal chain against the
    returned id and starts a simulation.
    """
    db = SessionLocal()
    try:
        scenario = Scenario(name=request.name.strip()[:200] or "Untitled scenario",
                            description=request.description)
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        return ScenarioCreateResponse(scenario_id=scenario.id, name=scenario.name)
    finally:
        db.close()
