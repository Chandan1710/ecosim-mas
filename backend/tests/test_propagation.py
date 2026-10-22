"""Event propagation: editable chains, the background brief, the API, and what a run picks up."""

import importlib.util
import os
import sys
import time
import types

os.environ.setdefault("ECOSIM_EMBEDDER", "hash")

# heavy optional packages that the older modules import at the top; only stubbed where they are not installed
for _name in ("sentence_transformers", "joblib"):
    if importlib.util.find_spec(_name) is None:
        _m = types.ModuleType(_name)
        _m.SentenceTransformer = object
        _m.load = lambda *a, **k: None
        sys.modules[_name] = _m

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import town.propagation as P
import town.runs as runs
from town.propagation_presets import PRESET_CHAINS
from town.scenarios import SCENARIO_ORDER


def N(i, deps=(), included=True, **kw):
    return {"id": i, "description": f"Event {i}", "category": "prices", "magnitude": "major", "confidence": 0.8,
            "depends_on": list(deps), "included": included, **kw}


# ── chain logic ─────────────────────────────────────────────────────────────
def test_every_preset_chain_is_sound():
    assert set(PRESET_CHAINS) == set(SCENARIO_ORDER)
    for pid in SCENARIO_ORDER:
        nodes = P.preset_record(pid)["nodes"]
        ids = {n["id"] for n in nodes}
        assert len(nodes) >= 5 and len(ids) == len(nodes)
        assert [n for n in nodes if not n["depends_on"]][0]["id"] == 1, "one trigger"
        assert all(set(n["depends_on"]) <= ids and n["id"] not in n["depends_on"] for n in nodes)
        assert all(all(d < n["id"] for d in n["depends_on"]) for n in nodes), "causes come before effects"
        assert any(len([m for m in nodes if n["id"] in m["depends_on"]]) > 1 for n in nodes) or pid == "none", "has a branch"
        assert P.preset_record(pid)["explain"] and P.preset_record(pid)["watch"]


def test_normalise_repairs_a_messy_chain():
    nodes = P.normalise_chain([
        {"id": 1, "description": "  Trigger ", "depends_on": [2]},        # 1 <-> 2 is a cycle
        {"id": 2, "description": "Effect", "depends_on": [1, 99, 2], "category": "nonsense", "magnitude": "huge"},
        {"id": 2, "description": "Duplicate id"},
        {"id": 5, "description": ""},                                      # empty: dropped
        "junk",
    ])
    assert [n["description"] for n in nodes] == ["Trigger", "Effect", "Duplicate id"]
    ids = [n["id"] for n in nodes]
    assert len(set(ids)) == 3
    by = {n["id"]: n for n in nodes}
    assert by[2]["category"] == "other" and by[2]["magnitude"] == "moderate"
    # no cycle and no dangling parent
    assert not (1 in by[2]["depends_on"] and 2 in by[1]["depends_on"])
    assert all(d in by for n in nodes for d in n["depends_on"])


def test_excluding_a_node_relinks_its_children_and_renumbers():
    chain = [N(1), N(2, [1], included=False), N(3, [2]), N(4, [1]), N(5, [3, 4])]
    kept = P.kept_chain(chain)
    assert [n["description"] for n in kept] == ["Event 1", "Event 3", "Event 4", "Event 5"]
    by = {n["description"]: n for n in kept}
    assert by["Event 3"]["depends_on"] == [by["Event 1"]["id"]]      # follows the excluded node's parent now
    assert sorted(by["Event 5"]["depends_on"]) == sorted([by["Event 3"]["id"], by["Event 4"]["id"]])
    assert [n["id"] for n in kept] == [1, 2, 3, 4]
    assert all(n["included"] for n in kept)


def test_a_chain_with_everything_excluded_is_empty():
    assert P.kept_chain([N(1, included=False)]) == []


def test_shock_adds_up_what_is_kept():
    d = lambda ess: {"discretionary_spend_pct": -0.1, "savings_rate_pct": 0.0, "essential_cost_index_pct": ess, "credit_availability_pct": -0.1}
    chain = [N(1, deltas=d(0.2)), N(2, [1], deltas=d(0.1)), N(3, [1], included=False, deltas=d(0.5)), N(4, [2])]
    r = P.shock_for_chain(chain)
    assert r["shock"]["essential_cost"] == pytest.approx(0.3) and r["quantified"] == 2 and r["pending"] == 1
    assert P.shock_for_chain(chain[:1])["shock"]["essential_cost"] == pytest.approx(0.2)


def test_template_brief_is_built_from_the_chain_only():
    out = P.template_brief({"title": "Oil shock"}, P.kept_chain([N(1), N(2, [1])]))
    assert "Event 2" in out["brief"] and out["headlines"] == ["Event 1", "Event 2"]


# ── the API, with a throwaway database ──────────────────────────────────────
@pytest.fixture()
def api(tmp_path, monkeypatch):
    import db.session as dbs
    from db.base_class import Base
    import models  # noqa: F401  (registers the tables)
    eng = create_engine(f"sqlite:///{tmp_path}/main.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    monkeypatch.setattr(dbs, "SessionLocal", sessionmaker(autocommit=False, autoflush=False, bind=eng))
    monkeypatch.setattr(runs, "RUNS_DIR", str(tmp_path / "runs"))
    from town import experience
    monkeypatch.setattr(experience, "_store", experience.ExperienceStore(f"sqlite:///{tmp_path}/exp.db"))
    P.reset_for_tests()

    # no network: a fixed chain, fixed numbers and a template brief
    import app.services.llm as llm
    monkeypatch.setattr(llm, "generate_causal_chain", lambda **kw: [
        {"node_id": 1, "description": "Oil jumps", "magnitude": "major", "category": "prices", "depends_on": [], "confidence": 0.9},
        {"node_id": 2, "description": "Transport costs rise", "magnitude": "major", "category": "trade", "depends_on": [1], "confidence": 0.8},
        {"node_id": 3, "description": "Factories cut shifts", "magnitude": "moderate", "category": "employment", "depends_on": [2], "confidence": 0.7},
        {"node_id": 4, "description": "Banks tighten loans", "magnitude": "moderate", "category": "credit", "depends_on": [1], "confidence": 0.7}])
    monkeypatch.setattr(llm, "map_node_to_deltas", lambda node, **kw: {"node_id": node["node_id"], "rationale": "r", "deltas": {
        "discretionary_spend_pct": -0.05, "savings_rate_pct": 0.01, "essential_cost_index_pct": 0.1, "credit_availability_pct": -0.05}})
    monkeypatch.setattr(P, "generate_brief", lambda rec, chain: {**P.template_brief(rec, chain), "source": "template"})
    monkeypatch.setattr(P, "generate_causal_chain", llm.generate_causal_chain, raising=False)
    import app.api.endpoints.propagation as ep
    app = FastAPI()
    app.include_router(ep.router)
    with TestClient(app) as c:
        yield c
    runs.manager.live.clear()
    P.reset_for_tests()


def _wait(client, key, until, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        rec = client.get(f"/town/propagation/{key}").json()
        if until(rec):
            return rec
        time.sleep(0.05)
    raise AssertionError(f"timed out: {rec.get('status')} {rec.get('job')}")


CREATE = {"description": "Crude oil jumps 30%", "primary_event": "Crude oil jumps 30%", "region": "India",
          "clarifications": [{"field": "duration", "question": "How long?", "answer": "three months"}]}


def test_list_has_all_presets_first_time(api):
    items = api.get("/town/propagation").json()["items"]
    assert [i["key"] for i in items] == [f"preset:{p}" for p in SCENARIO_ORDER]
    assert all(not i["editable"] and i["nodes"] and i["explain"] for i in items)


def test_create_edit_finalize_flow(api):
    rec = api.post("/town/propagation/custom", json=CREATE).json()
    key = rec["key"]
    assert key.startswith("custom:") and rec["status"] == "draft" and len(rec["nodes"]) == 4
    # the first chain is quantified in the background so the preview works while editing
    rec = _wait(api, key, lambda r: all(n.get("deltas") for n in r["nodes"]))
    assert api.post("/town/propagation/shock", json={"nodes": rec["nodes"]}).json()["pending"] == 0

    nodes = rec["nodes"]
    nodes[2]["included"] = False                                                   # exclude "Factories cut shifts"
    nodes.append({"id": 9, "description": "Households switch to buses", "category": "consumer_behaviour",
                  "magnitude": "minor", "confidence": 0.6, "depends_on": [2], "included": True, "added": True})
    before = api.post("/town/propagation/shock", json={"nodes": nodes}).json()
    assert before["nodes"] == 4 and before["pending"] == 1                          # new node has no numbers yet

    fin = api.post(f"/town/propagation/custom/{rec['scenario_id']}/finalize", json={"nodes": nodes, "clarifications": CREATE["clarifications"]})
    assert fin.status_code == 200 and fin.json()["status"] == "working"
    done = _wait(api, key, lambda r: r["status"] == "ready")
    assert done["brief"]["source"] == "template" and done["brief"]["headlines"]
    kept = P.kept_chain(done["nodes"])
    assert [n["description"] for n in kept] == ["Oil jumps", "Transport costs rise", "Banks tighten loans", "Households switch to buses"]
    assert all(n.get("deltas") for n in kept), "the added node was quantified before the brief"
    assert "Factories" not in done["brief"]["brief"]
    assert done["shock"]["essential_cost"] > 0
    # the older causal_chains table now holds exactly the chain that was kept
    import db.session as dbs
    from models.causal_chains import CausalChain
    db = dbs.SessionLocal()
    try:
        row = db.query(CausalChain).filter(CausalChain.scenario_id == rec["scenario_id"]).order_by(CausalChain.id.desc()).first()
        assert [n["description"] for n in row.chain] == [n["description"] for n in kept] and all("deltas" in n for n in row.chain)
    finally:
        db.close()
    # and a run started from it uses the brief's headlines and the kept numbers
    shock, heads, title = runs.scenario_from_db(rec["scenario_id"])
    assert heads == done["brief"]["headlines"] and shock.essential_cost == pytest.approx(0.4)

    items = api.get("/town/propagation").json()["items"]
    assert items[0]["key"] == key and items[0]["editable"]


def test_an_event_still_being_typed_does_not_break_preview_or_autosave(api):
    rec = api.post("/town/propagation/custom", json=CREATE).json()
    nodes = rec["nodes"] + [{"id": 9, "description": "", "depends_on": [2], "added": True}]
    assert api.post("/town/propagation/shock", json={"nodes": nodes}).status_code == 200
    saved = api.put(f"/town/propagation/custom/{rec['scenario_id']}", json={"nodes": nodes, "clarifications": []})
    assert saved.status_code == 200 and len(saved.json()["nodes"]) == 4, "the blank event is dropped, not stored"


def test_finalize_needs_a_kept_event_and_survives_a_running_job(api):
    rec = api.post("/town/propagation/custom", json=CREATE).json()
    sid = rec["scenario_id"]
    none = [{**n, "included": False} for n in rec["nodes"]]
    assert api.post(f"/town/propagation/custom/{sid}/finalize", json={"nodes": none}).status_code == 400
    # finalize straight away, while the first mapping job may still be running: both must complete
    assert api.post(f"/town/propagation/custom/{sid}/finalize", json={"nodes": rec["nodes"]}).status_code == 200
    done = _wait(api, rec["key"], lambda r: r["status"] == "ready")
    assert done["job"]["state"] == "done" and all(n.get("deltas") for n in done["nodes"])


def test_regenerate_and_forget(api):
    rec = api.post("/town/propagation/custom", json=CREATE).json()
    sid = rec["scenario_id"]
    again = api.post(f"/town/propagation/custom/{sid}/regenerate",
                     json={"clarifications": [{"field": "x", "question": "q", "answer": "a"}]}).json()
    assert again["status"] == "draft" and again["clarifications"][0]["answer"] == "a"
    assert api.delete(f"/town/propagation/custom/{sid}").json()["ok"]
    assert all(i["key"] != rec["key"] for i in api.get("/town/propagation").json()["items"])
    assert api.get("/town/propagation/preset:nope").status_code == 404


def test_keep_only_forgets_the_others_but_never_the_built_in_ones(api):
    a = api.post("/town/propagation/custom", json=CREATE).json()
    b = api.post("/town/propagation/custom", json=CREATE).json()
    c = api.post("/town/propagation/custom", json=CREATE).json()
    r = api.post(f"/town/propagation/custom/{b['scenario_id']}/keep-only").json()
    assert r == {"ok": True, "forgotten": 2}
    items = api.get("/town/propagation").json()["items"]
    assert [i["key"] for i in items if i["kind"] == "custom"] == [b["key"]]
    assert len([i for i in items if i["kind"] == "preset"]) == len(SCENARIO_ORDER)


def test_forget_many_hides_only_the_chosen_custom_scenarios(api):
    ids = [api.post("/town/propagation/custom", json=CREATE).json()["scenario_id"] for _ in range(3)]
    r = api.post("/town/propagation/forget", json={"scenario_ids": [ids[0], ids[2], 999]}).json()
    assert r == {"ok": True, "forgotten": 2}
    items = api.get("/town/propagation").json()["items"]
    assert [i["scenario_id"] for i in items if i["kind"] == "custom"] == [ids[1]]
    assert len([i for i in items if i["kind"] == "preset"]) == len(SCENARIO_ORDER)


def test_scenarios_from_before_this_page_are_imported_once(api):
    import db.session as dbs
    from models.causal_chains import CausalChain
    from models.scenarios import Scenario
    db = dbs.SessionLocal()
    try:
        sc = Scenario(name="Old onion ban", description="made before")
        db.add(sc)
        db.commit()
        db.add(CausalChain(scenario_id=sc.id, chain=[{"node_id": 1, "description": "Onion exports banned", "magnitude": "major",
                                                       "category": "trade", "depends_on": [], "confidence": 0.9}]))
        db.commit()
        key = f"custom:{sc.id}"
    finally:
        db.close()
    items = api.get("/town/propagation").json()["items"]
    assert items[0]["key"] == key and items[0]["title"] == "Old onion ban" and items[0]["status"] == "ready"
    api.delete(f"/town/propagation/custom/{key.split(':')[1]}")
    assert all(i["key"] != key for i in api.get("/town/propagation").json()["items"]), "a forgotten one stays forgotten"


def test_runs_are_linked_to_their_scenario():
    rec = {"kind": "preset", "preset_id": "war"}
    metas = [{"run_id": "a", "source": {"preset": "war"}, "created_at": 1}, {"run_id": "b", "source": {"preset": "none"}, "created_at": 2},
             {"run_id": "c", "source": {"preset": "war"}, "created_at": 3}]
    assert [r["run_id"] for r in P.runs_for(rec, metas)] == ["c", "a"]
    assert [r["run_id"] for r in P.runs_for({"kind": "custom", "scenario_id": 4},
                                            [{"run_id": "z", "source": {"scenario_id": 4}, "created_at": 1}])] == ["z"]
