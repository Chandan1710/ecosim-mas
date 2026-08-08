# Run the server from the backend/ directory with:
# uvicorn app.main:app --reload

from fastapi import FastAPI
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

from app.api.endpoints.scenarios import router as scenarios_router

app = FastAPI(title="EcoSim-MAS")

app.include_router(scenarios_router, prefix="/scenarios", tags=["scenarios"])
