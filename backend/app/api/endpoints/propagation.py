"""
Event propagation API.

  GET    /town/propagation                       every scenario (ready-made + yours) with its chain, brief and runs
  GET    /town/propagation/{key}                 one of them ("preset:severe" or "custom:12"); poll this while a job runs
  POST   /town/propagation/custom                start from a described scenario: Groq writes the first chain
  POST   /town/propagation/custom/{id}/regenerate  ask Groq for a new chain (e.g. after answering its questions)
  PUT    /town/propagation/custom/{id}           save the chain as edited so far (a draft)
  POST   /town/propagation/custom/{id}/finalize  the chain is final: quantify it and write the brief in the background
  DELETE /town/propagation/custom/{id}           forget a scenario's record
  POST   /town/propagation/shock                 the Shock a set of nodes adds up to (no LLM; for the live preview)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from town import propagation as P
from town.runs import manager

router = APIRouter(prefix="/town/propagation", tags=["event-propagation"])


class NodeIn(BaseModel):
    id: int
    description: str = Field(default="", max_length=400)  # a blank one is an event still being typed; normalise drops it
    category: str = "other"
    magnitude: str = "moderate"
    confidence: float = 0.7
    depends_on: List[int] = Field(default_factory=list)
    note: str = ""
    included: bool = True
    added: bool = False
    deltas: Optional[Dict[str, float]] = None
    rationale: Optional[str] = None


class Clarification(BaseModel):
    field: str = ""
    question: str = ""
    answer: str = ""


class CreateBody(BaseModel):
    description: str = Field(..., min_length=3)
    primary_event: str = Field(..., min_length=3)
    region: Optional[str] = None
    time_horizon_months: Optional[int] = None
    affected_sectors: List[str] = Field(default_factory=list)
    understood: List[str] = Field(default_factory=list)
    date: Optional[str] = None
    location: Optional[str] = None
    clarifications: List[Clarification] = Field(default_factory=list)


class RegenBody(BaseModel):
    clarifications: List[Clarification] = Field(default_factory=list)


class SaveBody(BaseModel):
    nodes: List[NodeIn]
    clarifications: Optional[List[Clarification]] = None
    title: Optional[str] = None


class ShockBody(BaseModel):
    nodes: List[NodeIn]


def _store():
    s = P.get_propagation_store()
    if s is None:
        raise HTTPException(503, "The database for saved scenarios is not reachable right now")
    return s


def _present(rec: dict, runs: List[dict]) -> dict:
    out = dict(rec)
    out["runs"] = P.runs_for(rec, runs)
    out["editable"] = rec["kind"] == "custom"
    out["working"] = rec["kind"] == "custom" and (P.job_running(rec["key"]) or rec.get("status") == "working")
    return out


def _with_answers(event: str, clars: List[Clarification]) -> str:
    bits = [f"{c.field.replace('_', ' ')}: {c.answer.strip()}" for c in clars if c.answer.strip()]
    return f"{event} ({'; '.join(bits)})" if bits else event


@router.get("")
def list_all():
    runs = manager.list_runs()
    items: List[dict] = []
    store = P.get_propagation_store()
    if store is not None:
        P.import_legacy(store)
        items += [_present(r, runs) for r in store.list("custom")]
    for pid in P.preset_ids():
        items.append(_present(P.preset_record(pid), runs))
    return {"items": items, "stored": store is not None}


@router.post("/shock")
def preview_shock(body: ShockBody):
    return P.shock_for_chain([n.model_dump() for n in body.nodes])


@router.get("/{key}")
def get_one(key: str):
    runs = manager.list_runs()
    if key.startswith("preset:"):
        rec = P.preset_record(key.split(":", 1)[1])
    else:
        rec = _store().get(key)
    if rec is None:
        raise HTTPException(404, f"No scenario '{key}'")
    return _present(rec, runs)


@router.post("/custom")
def create_custom(body: CreateBody):
    """Save the scenario, ask Groq for a first chain, and start quantifying it in the background."""
    store = _store()
    from db.session import SessionLocal
    from models.scenarios import Scenario
    from app.services.llm import generate_causal_chain
    db = SessionLocal()
    try:
        sc = Scenario(name=body.primary_event.strip()[:200], description=body.description)
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sid = sc.id
    finally:
        db.close()
    raw = generate_causal_chain(primary_event=_with_answers(body.primary_event, body.clarifications), region=body.region,
                                time_horizon_months=body.time_horizon_months, affected_sectors=body.affected_sectors,
                                date_override=body.date, location_override=body.location)
    rec = {"key": f"custom:{sid}", "kind": "custom", "scenario_id": sid, "title": body.primary_event.strip(),
           "description": body.description.strip(), "region": body.region, "time_horizon_months": body.time_horizon_months,
           "affected_sectors": body.affected_sectors, "understood": body.understood, "date": body.date, "location": body.location,
           "clarifications": [c.model_dump() for c in body.clarifications], "nodes": P.from_llm_chain(raw),
           "status": "draft", "job": {"state": "idle", "message": ""}, "brief": None, "headlines": []}
    store.save(rec)
    P.start_job(rec["key"], brief=False)
    return _present(rec, [])


def _custom(sid: int) -> dict:
    rec = _store().get(f"custom:{sid}")
    if rec is None:
        raise HTTPException(404, f"No scenario {sid}")
    return rec


@router.post("/custom/{sid}/regenerate")
def regenerate(sid: int, body: RegenBody):
    from app.services.llm import generate_causal_chain
    rec = _custom(sid)
    raw = generate_causal_chain(primary_event=_with_answers(rec["title"], body.clarifications), region=rec.get("region"),
                                time_horizon_months=rec.get("time_horizon_months"),
                                affected_sectors=rec.get("affected_sectors") or [],
                                date_override=rec.get("date"), location_override=rec.get("location"))
    rec = _store().patch(rec["key"], nodes=P.from_llm_chain(raw), clarifications=[c.model_dump() for c in body.clarifications],
                         status="draft", brief=None, headlines=[])
    P.start_job(rec["key"], brief=False)
    return _present(rec, [])


def _apply(rec: dict, body: SaveBody) -> dict:
    nodes = P.normalise_chain([n.model_dump() for n in body.nodes])
    if not nodes:
        raise HTTPException(400, "The chain has no events")
    fields: Dict[str, Any] = {"nodes": nodes}
    if body.clarifications is not None:
        fields["clarifications"] = [c.model_dump() for c in body.clarifications]
    if body.title and body.title.strip():
        fields["title"] = body.title.strip()[:240]
    return fields


@router.put("/custom/{sid}")
def save_draft(sid: int, body: SaveBody):
    rec = _custom(sid)
    rec = _store().patch(rec["key"], **_apply(rec, body), status="draft" if rec.get("status") != "ready" else "ready")
    if any(n["included"] and not n.get("deltas") for n in rec["nodes"]):
        P.start_job(rec["key"], brief=False)       # quantify any new events while the user keeps editing
    return _present(rec, [])


@router.post("/custom/{sid}/finalize")
def finalize(sid: int, body: SaveBody):
    rec = _custom(sid)
    fields = _apply(rec, body)
    if not P.kept_chain(fields["nodes"]):
        raise HTTPException(400, "Keep at least one event in the chain")
    rec = _store().patch(rec["key"], **fields, status="working", brief=None, headlines=[],
                         job={"state": "queued", "message": "Waiting to start"})
    P.start_job(rec["key"], brief=True)
    return _present(rec, [])


class ForgetManyBody(BaseModel):
    scenario_ids: List[int] = Field(default_factory=list)


@router.post("/forget")
def forget_many(body: ForgetManyBody):
    """Hide several of your own scenarios at once (their runs stay in Recent runs). Built-in ones cannot be hidden."""
    store = _store()
    n = 0
    for sid in set(body.scenario_ids):
        rec = store.get(f"custom:{sid}")
        if rec is not None:
            store.patch(rec["key"], status="hidden")
            n += 1
    return {"ok": True, "forgotten": n}


@router.post("/custom/{sid}/keep-only")
def keep_only(sid: int):
    """Forget every one of your scenarios except this one (the built-in ones are never touched)."""
    keep = _custom(sid)
    store = _store()
    gone = [r for r in store.list("custom") if r["key"] != keep["key"]]
    for r in gone:
        store.patch(r["key"], status="hidden")
    return {"ok": True, "forgotten": len(gone)}


@router.delete("/custom/{sid}")
def forget(sid: int):
    rec = _custom(sid)
    _store().patch(rec["key"], status="hidden")      # kept, but no longer listed (and not re-imported)
    return {"ok": True}
