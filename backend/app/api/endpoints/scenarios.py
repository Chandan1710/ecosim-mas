from fastapi import APIRouter
from app.api.endpoints.models import ScenarioParseRequest, ScenarioParseResponse
from app.services.llm import parse_scenario_with_llm

router = APIRouter()

@router.post("/parse", response_model=ScenarioParseResponse)
def parse_scenario(request: ScenarioParseRequest):
    return parse_scenario_with_llm(
        description=request.description,
        date_override=request.date_override,
        location_override=request.location_override
    )
