# Run the server from the backend/ directory with:
# uvicorn app.main:app --reload

from fastapi import FastAPI
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

from app.api.endpoints.scenarios import router as scenarios_router
from app.api.endpoints.causal_chains import router as causal_chains_router

app = FastAPI(title="EcoSim-MAS")

app.include_router(scenarios_router, prefix="/scenarios", tags=["scenarios"])
app.include_router(causal_chains_router, prefix="/scenarios", tags=["causal-chains"])
