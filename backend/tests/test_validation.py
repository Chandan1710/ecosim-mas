"""Validation mode: real events with published figures, a town run on the inputs only, a scorecard of the results."""

import os
import time

os.environ.setdefault("ECOSIM_EMBEDDER", "hash")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import town.runs as runs
from app.api.endpoints.town import router
from town import validation as V
from town.validation_events import EVENTS


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", str(tmp_path))
    runs.manager.live.clear()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    runs.manager.live.clear()


def _wait(client, rid, limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        if client.get(f"/town/runs/{rid}").json()["status"] != "running":
            return
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_every_built_in_event_is_complete_and_sourced():
    assert len(EVENTS) >= 2
    for e in EVENTS:
        assert e["inputs"] and e["outcomes"] and e["run"]["days"] >= 10
        for o in e["outcomes"]:
            assert o["measure"] in V.MEASURES and o["group"] in V.GROUPS
            assert o["source"].strip() and o["url"].startswith("https://")
            assert isinstance(o["real"], (int, float))
        # inputs and outcomes must not overlap: the town is never told what happened
        assert not {"jobless_rise", "food_short", "borrowed", "income_change", "spending_change"} & set(e["inputs"])


def test_judging_uses_a_band_and_direction():
    assert V.band_for(10) == 7.5 and V.band_for(74) == 18.5
    assert V.judge(37, 40)["verdict"] == "close"
    assert V.judge(37, 37 + 9.2 + 3)["verdict"] == "roughly"
    assert V.judge(37, 90)["verdict"] == "off"
    assert V.judge(-26.7, -30)["verdict"] == "close"
    assert V.judge(-26.7, -50)["verdict"] == "off"                    # more than two bands away
    assert V.judge(-26.7, -26.7 + 12)["verdict"] == "roughly"
    assert V.judge(-26.7, +5)["verdict"] == "off"                     # the wrong way
    assert V.judge(5, None)["verdict"] == "unknown"


def test_net_effect_is_the_difference_from_the_no_shock_town():
    assert V.net_effect("borrowed", 60.0, 20.0) == 40.0
    assert V.net_effect("spending_change", -58.4, -43.4) == pytest.approx(-26.5, abs=0.1)   # ratio of the two, not the difference
    assert V.net_effect("food_short", None, 20.0) is None


def test_custom_event_needs_a_real_figure_and_clamps_inputs():
    with pytest.raises(ValueError):
        V.event_from_custom({"title": "x", "outcomes": [{"measure": "borrowed", "real": ""}]})
    e = V.event_from_custom({"title": "x", "inputs": {"essential_cost": 3}, "outcomes": [{"measure": "borrowed", "real": 30, "source": "my survey"}]})
    assert e["inputs"]["essential_cost"] == 0.6 and e["outcomes"][0]["source"] == "my survey"
    shock, rules = V.inputs_to_shock({"essential_cost": 0.2, "demand": -0.2, "lockdown": True})
    assert shock.essential_cost == 0.2 and shock.income == pytest.approx(-0.1) and rules.lockdown


def test_events_endpoint_lists_events_measures_and_the_band(client):
    d = client.get("/town/validation/events").json()
    assert {e["id"] for e in d["events"]} >= {"covid-2020", "covid-2021"}
    assert set(d["measures"]) == set(V.MEASURES) and d["band"]["min"] == V.MIN_BAND


def test_a_validation_run_ends_in_a_scorecard(client):
    r = client.post("/town/validation/run", json={"event_id": "covid-2021", "days": 8, "brain": "mock"})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    assert r.json()["source"] == {"validation": "covid-2021"} and r.json()["title"].startswith("Validation:")
    _wait(client, rid)
    card = client.get(f"/town/runs/{rid}/validation").json()
    assert card["event"]["id"] == "covid-2021" and card["rows"]
    row = card["rows"][0]
    assert row["real"] == 3.9 and row["sim"] is not None and row["verdict"] in ("close", "roughly", "off")
    assert row["control"] is not None and "source" in row
    assert card["score"] in (0, 50, 100) and card["verdict"] in ("close", "roughly", "off")
    # it shows up in the validation list, with its score, and in the ordinary run list
    lst = client.get("/town/validation/runs").json()
    assert lst and lst[0]["run_id"] == rid and lst[0]["score"] == card["score"]
    assert any(m["run_id"] == rid for m in client.get("/town/runs").json())


def test_a_custom_event_runs_with_the_inputs_only(client):
    body = {"title": "Fuel rise", "inputs": {"essential_cost": 0.3}, "days": 8, "brain": "mock",
            "outcomes": [{"measure": "borrowed", "real": 30, "group": "all", "source": "my survey"}]}
    r = client.post("/town/validation/run", json=body)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    assert r.json()["shock"]["essential_cost"] == 0.3
    _wait(client, rid)
    card = client.get(f"/town/runs/{rid}/validation").json()
    assert card["event"]["custom"] and card["rows"][0]["real"] == 30 and card["rows"][0]["source"] == "my survey"


def test_bad_requests(client):
    assert client.post("/town/validation/run", json={"event_id": "nope"}).status_code == 404
    assert client.post("/town/validation/run", json={"title": "x", "outcomes": []}).status_code == 400
    rid = client.post("/town/runs", json={"preset": "none", "days": 5, "brain": "mock"}).json()["run_id"]
    _wait(client, rid)
    assert client.get(f"/town/runs/{rid}/validation").status_code == 404          # an ordinary run has no scorecard
