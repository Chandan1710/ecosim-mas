"""
Town API: start a run, stream it, replay it, and get both PDF reports.
Uses the offline mock brain and in-process memory, so it needs no keys or services.
"""

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


def _wait_done(client, run_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        meta = client.get(f"/town/runs/{run_id}").json()
        if meta["status"] != "running":
            return meta
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_map_and_presets(client):
    m = client.get("/town/map").json()
    assert m["width"] == 64 and len(m["places"]) == 20
    ids = [p["id"] for p in client.get("/town/presets").json()]
    assert ids == ["severe", "pandemic", "war", "disaster", "hyperinflation", "none", "lockdown"]


def test_run_stream_replay_and_reports(client, tmp_path):
    r = client.post("/town/runs", json={"preset": "severe", "days": 6, "brain": "mock", "seed": 3})
    assert r.status_code == 200, r.text
    meta = r.json()
    run_id = meta["run_id"]
    assert meta["pace"] == "fast" and meta["status"] == "running"

    # one run at a time (shared API keys)
    assert client.post("/town/runs", json={"preset": "mild", "days": 3, "brain": "mock"}).status_code == 409

    # the live stream delivers everything from run_start to run_end, in order
    with client.websocket_connect(f"/ws/town/{run_id}") as ws:
        types = []
        while True:
            ev = ws.receive_json()
            types.append(ev["type"])
            if ev["type"] == "stream_end":
                break
    assert types[0] == "run_start" and "run_end" in types and types.count("day_end") == 6

    meta = _wait_done(client, run_id)
    assert meta["status"] == "done" and meta["days_done"] == 6

    # saved, listed, replayable
    assert os.path.exists(tmp_path / f"{run_id}.jsonl")
    assert client.get("/town/runs").json()[0]["run_id"] == run_id
    events = client.get(f"/town/runs/{run_id}/events").json()
    assert events[0]["type"] == "run_start" and events[0]["shock_onset_day"] == 2
    runs.manager.live.clear()                       # as after a server restart: replay comes from disk
    with client.websocket_connect(f"/ws/town/{run_id}") as ws:
        n = 0
        while ws.receive_json()["type"] != "stream_end":
            n += 1
    assert n == len(events)

    a = client.get(f"/town/runs/{run_id}/analysis").json()
    assert len(a["agents"]) == 20 and a["days_run"] == 6
    assert sum(a["status_counts"].values()) == 20

    for kind in ("summary", "agents"):
        pdf = client.get(f"/town/runs/{run_id}/report/{kind}")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert "attachment" in pdf.headers["content-disposition"]


def test_agent_profiles(client):
    r = client.get("/town/agents?seed=7&n=20")
    assert r.status_code == 200
    people = r.json()
    assert len(people) == 20
    p = people[0]
    for key in ("id", "name", "age", "gender", "job_key", "job_title", "home_name", "bio", "goals", "loans", "relations"):
        assert key in p
    assert all(rel["name"] for a in people for rel in a["relations"])
    # the same seed always gives the same town
    assert [a["name"] for a in client.get("/town/agents?seed=7&n=20").json()] == [a["name"] for a in people]


def test_stop_a_live_run(client):
    run_id = client.post("/town/runs", json={"preset": "severe", "days": 40, "brain": "mock"}).json()["run_id"]
    time.sleep(0.3)
    r = client.post(f"/town/runs/{run_id}/stop")
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    # a new run can start now
    r2 = client.post("/town/runs", json={"preset": "none", "days": 2, "brain": "mock"})
    assert r2.status_code == 200
    _wait_done(client, r2.json()["run_id"])


def test_unknown_run_and_bad_preset(client):
    assert client.get("/town/runs/nope").status_code == 404
    assert client.post("/town/runs", json={"preset": "apocalypse", "brain": "mock"}).status_code == 400


def test_learning_endpoints(client):
    first = client.post("/town/runs", json={"preset": "lockdown", "days": 6, "brain": "mock", "learning": "learn"}).json()
    assert first["learning"] == "learn"
    meta = _wait_done(client, first["run_id"])
    assert meta["learning_summary"]["mode"] == "learn"
    got = client.get("/town/learning").json()
    assert got["available"] and got["counts"]["town_experience"] > 0
    assert len(got["agents"]) == 20 and got["agents"]["a01"]["runs"]
    off = client.post("/town/runs", json={"preset": "none", "days": 3, "brain": "mock", "learning": "off"}).json()
    assert off["learning"] == "off"
    _wait_done(client, off["run_id"])
    assert client.post("/town/learning/reset", json={"agent": "nobody"}).status_code == 404
    assert client.post("/town/learning/reset", json={}).json()["ok"]
    assert client.get("/town/learning").json()["counts"]["town_experience"] == 0
