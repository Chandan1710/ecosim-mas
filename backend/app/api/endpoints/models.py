from pydantic import BaseModel
from typing import List, Optional

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
