"""The Dashboard endpoint: one run boiled down, with its scenario's chain and brief."""

import os
import time

os.environ.setdefault("ECOSIM_EMBEDDER", "hash")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import town.runs as runs
from app.api.endpoints.town import router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", str(tmp_path))
    runs.manager.live.clear()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    runs.manager.live.clear()


def _run(client, **body):
    r = client.post("/town/runs", json={"preset": "severe", "days": 5, "brain": "mock", "seed": 3, **body})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    t0 = time.time()
    while time.time() - t0 < 60:
        if client.get(f"/town/runs/{rid}").json()["status"] != "running":
            return rid
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_dashboard_has_results_series_and_the_scenario_chain(client):
    rid = _run(client)
    d = client.get(f"/town/runs/{rid}/dashboard").json()
    assert d["run"]["run_id"] == rid and d["run"]["status"] == "done" and d["run"]["days_run"] == 5
    assert [r["day"] for r in d["series"]] == [1, 2, 3, 4, 5]
    assert {"avg_money", "low_food", "defaulted", "unemployed", "moneylender", "groceries", "fuel", "avg_reward"} <= set(d["series"][0])
    assert len(d["agents"]) == 20 and all(len(a["money_series"]) == 5 for a in d["agents"])
    assert sum(d["status_counts"].values()) == 20
    assert d["findings"] and all(isinstance(s, str) for s in d["findings"])
    assert d["kpis"]["avg_money_end"] > 0
    # the preset's hand-written chain rides along
    p = d["propagation"]
    assert p["key"] == "preset:severe" and len(p["nodes"]) >= 5 and p["explain"] and p["watch"]
    assert "pivots" not in d["agents"][0] and "talks" not in d["agents"][0], "the page gets a trimmed resident, not the full case file"


def test_dashboard_for_an_unknown_run_is_404_and_for_an_unscenario_run_has_no_chain(client, monkeypatch):
    assert client.get("/town/runs/nope/dashboard").status_code == 404
    rid = _run(client, preset="none", days=3)
    d = client.get(f"/town/runs/{rid}/dashboard").json()
    assert d["run"]["source"] == {"preset": "none"} and d["propagation"]["key"] == "preset:none"
