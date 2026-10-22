"""POST /scenarios creates a scenario row the intake flow can build a chain on."""

from fastapi.testclient import TestClient

from app.main import app
from db.session import SessionLocal
from models.scenarios import Scenario


def test_create_scenario_persists_a_row():
    client = TestClient(app)
    resp = client.post("/scenarios", json={"name": "RBI hikes repo by 100 bps",
                                           "description": "Full description here"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "RBI hikes repo by 100 bps"

    db = SessionLocal()
    try:
        row = db.query(Scenario).filter(Scenario.id == body["scenario_id"]).first()
        assert row is not None and row.description == "Full description here"
    finally:
        db.close()


def test_create_scenario_requires_a_name():
    assert TestClient(app).post("/scenarios", json={}).status_code == 422
