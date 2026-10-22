"""
Town of generative agents — HTTP + WebSocket API (ARCHITECTURE §7.6).

  GET  /town/map                         the town layout (roads, buildings)
  GET  /town/presets                     ready-made shocks for quick runs
  GET  /town/agents                      the town's residents (profiles) for a given seed
  POST /town/runs                        start a run (preset or scenario_id); one at a time
  GET  /town/runs                        saved runs, newest first
  GET  /town/runs/{id}                   one run's settings and status
  GET  /town/runs/{id}/events            the full event log (for replay)
  GET  /town/runs/{id}/analysis          computed findings (dashboard)
  GET  /town/runs/{id}/dashboard         everything the Dashboard page shows for one run
  GET  /town/validation/events           real events the town can be checked against (with sources)
  POST /town/validation/run              start a validation run (built-in event or your own figures)
  GET  /town/validation/runs             validation runs, newest first, with their match score
  GET  /town/runs/{id}/validation        the scorecard for one validation run
  POST /town/runs/{id}/stop              stop a live run
  GET  /town/runs/{id}/report/summary    1-2 page PDF
  GET  /town/runs/{id}/report/agents     per-agent PDF
  WS   /ws/town/{id}                     events so far, then live until the run ends
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from simulation.shock import describe
from town.runs import manager
from town.scenarios import SCENARIO_ORDER, SCENARIOS
from town.population import generate_population
from town.world import PLACES, map_json

logger = logging.getLogger(__name__)
router = APIRouter()


class StartRun(BaseModel):
    preset: Optional[str] = Field(None, description="one of the ids from GET /town/presets (ignored if scenario_id is given)")
    scenario_id: Optional[int] = None
    title: Optional[str] = None
    days: int = Field(10, ge=1, le=60)
    pace: Optional[str] = Field(None, description="fast | normal; default fast for runs of 10 days or fewer")
    seed: int = 7
    agents: int = Field(20, ge=2, le=25)
    brain: str = Field("auto", description="auto | llm | mock")
    learning: str = Field("learn", description="off = fresh agents | learn = use and add to what they learned | frozen = use only")


@router.get("/town/map")
def town_map():
    return map_json()


@router.get("/town/presets")
def presets():
    return [{"id": k, "title": SCENARIOS[k].title, "blurb": SCENARIOS[k].blurb, "shock": SCENARIOS[k].shock.to_dict(),
             "text": describe(SCENARIOS[k].shock), "headlines": list(SCENARIOS[k].headlines),
             "rules": SCENARIOS[k].rules.describe(), "tags": SCENARIOS[k].rules.tags()} for k in SCENARIO_ORDER]


@router.get("/town/agents")
def town_agents(seed: int = 7, n: int = 20):
    """Everyone who lives in the town, as they are on day 0 (profiles page)."""
    n = max(2, min(n, 25))
    agents = generate_population(n, seed)
    names = {a.id: a.name for a in agents}
    name_of = lambda pid: PLACES[pid].name if pid in PLACES else None  # noqa: E731
    out = []
    for a in agents:
        d = a.public_state()
        d["home_name"] = name_of(a.home)
        d["workplace_name"] = name_of(a.workplace) if a.workplace else None
        d["relations"] = [{"id": k, "name": names.get(k, k), "relation": v} for k, v in a.knows.items() if k in names]
        out.append(d)
    return out


@router.get("/town/learning")
async def town_learning(seed: int = 7, n: int = 20):
    """What each resident has learned across runs: reward per run, lessons, whom they trust."""
    from town.experience import get_store, last_error
    from town.learning import learning_summary
    store = await asyncio.get_running_loop().run_in_executor(None, get_store)
    if store is None:
        return {"available": False, "error": last_error(), "agents": {}}
    n = max(2, min(n, 25))
    out = await asyncio.get_running_loop().run_in_executor(None, learning_summary, store, generate_population(n, seed), seed)
    return {"available": True, **out}


class ResetLearning(BaseModel):
    agent: Optional[str] = Field(None, description="agent id to forget; leave out to reset everyone")
    seed: int = 7
    n: int = 20


@router.post("/town/learning/reset")
async def reset_learning(body: ResetLearning):
    from town.experience import get_store
    from town.learning import agent_key
    store = await asyncio.get_running_loop().run_in_executor(None, get_store)
    if store is None:
        raise HTTPException(503, "The learning database is not available")
    key = None
    if body.agent:
        a = next((x for x in generate_population(max(2, min(body.n, 25)), body.seed) if x.id == body.agent), None)
        if a is None:
            raise HTTPException(404, f"No resident {body.agent}")
        key = agent_key(body.seed, a)
    await asyncio.get_running_loop().run_in_executor(None, store.reset, key)
    return {"ok": True, "scope": body.agent or "everyone"}


@router.post("/town/runs")
async def start_run(body: StartRun):
    if manager.active() is not None:
        raise HTTPException(409, f"A run is already in progress ({manager.active().run_id}). "
                                 "Open it, or stop it before starting another.")
    try:
        if body.scenario_id is not None:
            # mapping the chain may call the LLM and the database: keep it off the event loop
            shock, heads, title, source = await asyncio.get_running_loop().run_in_executor(
                None, manager.resolve, None, body.scenario_id)
        else:
            shock, heads, title, source = manager.resolve(body.preset, None)
    except (LookupError, ValueError) as e:
        raise HTTPException(400, str(e))
    pace = body.pace or ("fast" if body.days <= 10 else "normal")
    try:
        meta = await manager.start(shock=shock, headlines=heads, title=body.title or title, source=source,
                                   days=body.days, pace=pace, seed=body.seed, n_agents=body.agents,
                                   brain_kind=body.brain, rules=manager.rules_for(source),
                                   learning=body.learning if body.learning in ("off", "learn", "frozen") else "learn")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:   # e.g. 'llm' brain requested with no keys
        raise HTTPException(400, str(e))
    return meta


@router.get("/town/runs")
def list_runs():
    return manager.list_runs()


def _meta_or_404(run_id: str) -> dict:
    meta = manager.get_meta(run_id)
    if meta is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return meta


@router.get("/town/runs/{run_id}")
def get_run(run_id: str):
    return _meta_or_404(run_id)


@router.get("/town/runs/{run_id}/events")
def get_events(run_id: str):
    _meta_or_404(run_id)
    return manager.events(run_id)


@router.get("/town/runs/{run_id}/analysis")
def get_analysis(run_id: str):
    from town.analysis import analyse
    meta = _meta_or_404(run_id)
    try:
        return analyse(manager.events(run_id), meta)
    except ValueError as e:
        raise HTTPException(409, str(e))


def _record_for(meta: dict):
    """The scenario record (event chain, brief) a run was started from, or None."""
    try:
        import town.propagation as P
        src = meta.get("source") or {}
        if src.get("preset"):
            return P.preset_record(src["preset"])
        if src.get("scenario_id") is not None:
            store = P.get_propagation_store()
            if store is None:
                return None
            rec = store.get(f"custom:{src['scenario_id']}")
            if rec is None:
                P.import_legacy(store)
                rec = store.get(f"custom:{src['scenario_id']}")
            return rec
    except Exception:
        logger.exception("could not load the scenario for run %s", meta.get("run_id"))
    return None


@router.get("/town/runs/{run_id}/dashboard")
def get_dashboard(run_id: str):
    from town.dashboard import build
    meta = _meta_or_404(run_id)
    try:
        return build(manager.events(run_id), meta, _record_for(meta))
    except ValueError as e:
        raise HTTPException(409, str(e))


# ── validation mode: does the town land roughly where the real event did? ────────
class ValidationOutcome(BaseModel):
    measure: str
    real: float
    group: str = "all"
    source: str = ""


class ValidationInputs(BaseModel):
    lockdown: bool = False
    essential_cost: float = Field(0.0, ge=-0.6, le=0.6, description="+0.2 = essentials 20% dearer")
    demand: float = Field(0.0, ge=-0.6, le=0.6, description="-0.2 = people cut spending by a fifth")
    credit_tightness: float = Field(0.0, ge=-0.6, le=0.6, description="+0.3 = banks lend much less")


class ValidationRun(BaseModel):
    event_id: Optional[str] = Field(None, description="a built-in event id; leave empty for your own")
    title: Optional[str] = None
    summary: Optional[str] = None
    inputs: Optional[ValidationInputs] = None
    outcomes: list = Field(default_factory=list)
    days: Optional[int] = Field(None, ge=5, le=60)
    brain: str = "auto"


@router.get("/town/validation/events")
def validation_events():
    from town import validation as V
    return {"events": V.catalogue(),
            "measures": {k: {"label": m["label"], "unit": m["unit"], "how": m["how"]} for k, m in V.MEASURES.items()},
            "groups": V.GROUPS, "band": {"min": V.MIN_BAND, "relative": V.REL_BAND}}


def _event_of(meta: dict) -> Optional[dict]:
    from town import validation as V
    src = (meta or {}).get("source") or {}
    if not src.get("validation"):
        return None
    if src["validation"] == "custom":
        return src.get("event")
    return V.BY_ID.get(src["validation"])


@router.post("/town/validation/run")
async def start_validation(body: ValidationRun):
    from town import validation as V
    try:
        if body.event_id:
            event = V.lookup(body.event_id)
        else:
            event = V.event_from_custom({"title": body.title, "summary": body.summary, "days": body.days,
                                         "inputs": body.inputs.model_dump() if body.inputs else {}, "outcomes": body.outcomes})
        shock, rules = V.inputs_to_shock(event["inputs"])
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    if manager.active() is not None:
        raise HTTPException(409, f"A run is already in progress ({manager.active().run_id}). Open it, or stop it before starting another.")
    days = body.days or event["run"]["days"]
    source = {"validation": event["id"]}
    if event.get("custom"):
        source["event"] = event
    try:
        meta = await manager.start(shock=shock, headlines=[event["title"]], title=f"Validation: {event['title']}", source=source,
                                   days=days, pace=event["run"]["pace"], seed=7, n_agents=20, brain_kind=body.brain,
                                   rules=rules, learning="off")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))
    return meta


async def _scorecard_for(meta: dict) -> dict:
    from town import validation as V
    event = _event_of(meta)
    if event is None:
        raise HTTPException(404, "This is not a validation run")
    run_id = meta["run_id"]
    loop = asyncio.get_running_loop()

    def work():
        events = manager.events(run_id)
        start = next((e for e in events if e.get("type") == "run_start"), None)
        if start is None:
            raise ValueError("The run has not produced any events yet")
        ctl = V.control_events(int(start.get("days") or meta.get("days") or 30), start.get("pace", "fast"),
                               int(meta.get("seed") or 7), int(meta.get("n_agents") or 20))
        card = V.scorecard(event, events, meta, ctl)
        days_run = sum(1 for e in events if e.get("type") == "day_end")
        return {**card, "run": {"run_id": run_id, "status": meta.get("status"), "days": meta.get("days"), "days_done": days_run,
                                "brain": meta.get("brain"), "created_at": meta.get("created_at")}}
    try:
        return await loop.run_in_executor(None, work)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/town/runs/{run_id}/validation")
async def get_validation(run_id: str):
    return await _scorecard_for(_meta_or_404(run_id))


@router.get("/town/validation/runs")
async def list_validation_runs():
    out = []
    for m in manager.list_runs():
        if not (m.get("source") or {}).get("validation"):
            continue
        row = {"run_id": m["run_id"], "title": m["title"], "status": m["status"], "created_at": m.get("created_at"),
               "days": m.get("days"), "days_done": m.get("days_done"), "brain": m.get("brain"),
               "event_id": m["source"]["validation"], "score": None, "verdict": None}
        if m["status"] in ("done", "stopped"):
            try:
                card = await _scorecard_for(m)
                row["score"], row["verdict"] = card["score"], card["verdict"]
            except HTTPException:
                pass
        out.append(row)
    return out


@router.post("/town/runs/{run_id}/stop")
async def stop_run(run_id: str):
    _meta_or_404(run_id)
    if not await manager.stop(run_id):
        raise HTTPException(409, "That run is not running")
    return manager.get_meta(run_id)


def _pdf(run_id: str, kind: str):
    from town.report import agents_pdf, summary_pdf
    meta = _meta_or_404(run_id)
    if meta.get("status") == "running":
        raise HTTPException(409, "The run is still going; the report is ready when it finishes")
    try:
        data = (summary_pdf if kind == "summary" else agents_pdf)(run_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    slug = "".join(c if c.isalnum() else "-" for c in (meta.get("title") or "run").lower()).strip("-")[:40]
    name = f"ecosim-{slug}-{run_id}-{kind}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/town/runs/{run_id}/report/summary")
def report_summary(run_id: str):
    return _pdf(run_id, "summary")


@router.get("/town/runs/{run_id}/report/agents")
def report_agents(run_id: str):
    return _pdf(run_id, "agents")


@router.websocket("/ws/town/{run_id}")
async def ws_town(websocket: WebSocket, run_id: str):
    await websocket.accept()
    if manager.get_meta(run_id) is None:
        await websocket.send_json({"type": "error", "message": f"Run {run_id} not found"})
        await websocket.close()
        return
    try:
        async for ev in manager.subscribe(run_id):
            await websocket.send_json(ev)
        await websocket.send_json({"type": "stream_end", "status": (manager.get_meta(run_id) or {}).get("status")})
        await websocket.close()
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass   # client went away mid-send
