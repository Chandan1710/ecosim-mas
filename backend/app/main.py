# Run the server from the backend/ directory with:
# uvicorn app.main:app --reload

from fastapi import FastAPI
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

from app.api.endpoints.scenarios import router as scenarios_router
from app.api.endpoints.causal_chains import router as causal_chains_router
from app.api.endpoints.map import router as map_router
from app.api.endpoints.predict import router as predict_router
from app.api.endpoints.simulate import router as simulate_router

app = FastAPI(title="EcoSim-MAS")

app.include_router(scenarios_router, prefix="/scenarios", tags=["scenarios"])
app.include_router(causal_chains_router, prefix="/scenarios", tags=["causal-chains"])
app.include_router(map_router, prefix="/scenarios", tags=["causal-chain-mapper"])
app.include_router(predict_router, prefix="/predict", tags=["ml-prediction"])
# simulate_router carries both the POST /scenarios/{id}/simulate/start route
# and the WebSocket /ws/simulate/{run_id} route
app.include_router(simulate_router, tags=["simulation"])
