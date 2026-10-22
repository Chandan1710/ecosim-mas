"""
propagation.py — event propagation: how a shock spreads, kept as an editable chain of events.

A *chain* is a small graph of events. Each node says what happens, its category and size, and which earlier
nodes it follows from (one parent: a straight line; two children: a branch; two parents: a merge).

For your own scenarios the flow is:

    describe → Groq writes a first chain → you add, edit, exclude or delete nodes → "Run"
    → in the background Groq (1) quantifies any node it has not seen (the numbers that become the Shock) and
      (2) writes a detailed simulation brief + a news timeline from exactly the chain you kept
    → the town run uses that Shock and those headlines.

The seven ready-made scenarios have hand-written chains (propagation_presets.py) that match what the simulator
actually does. Everything is kept in the same database as the agents' learning (see experience.py), so the
Event propagation page can list every scenario and its chain whenever you open it.

Record keys:  "preset:<id>"  or  "custom:<scenario_id>".
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, insert, select, update

logger = logging.getLogger(__name__)

CATEGORIES = ("prices", "employment", "credit", "policy", "consumer_behaviour", "trade", "other")
MAGNITUDES = ("major", "moderate", "minor")
MAX_NODES = 30
MAX_HEADLINES = 8

metadata = MetaData()
propagation = Table(
    "town_propagation", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(60), nullable=False, unique=True, index=True),
    Column("kind", String(12), nullable=False),
    Column("title", String(240)),
    Column("status", String(12)),
    Column("data", Text),            # the whole record as JSON
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)


# ── chains ──────────────────────────────────────────────────────────────────
def _clean_text(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def normalise_chain(nodes: Any) -> List[dict]:
    """Make any chain safe: unique integer ids, valid categories, no self-loops or cycles, at most MAX_NODES."""
    out: List[dict] = []
    seen = set()
    for raw in (nodes or []) if isinstance(nodes, list) else []:
        if not isinstance(raw, dict):
            continue
        desc = _clean_text(raw.get("description", raw.get("label", "")), 220)
        if not desc:
            continue
        try:
            nid = int(raw.get("id", raw.get("node_id")))
        except (TypeError, ValueError):
            nid = (max(seen) + 1) if seen else 1
        while nid in seen:
            nid += 1
        seen.add(nid)
        cat = str(raw.get("category", "other"))
        mag = str(raw.get("magnitude", "moderate"))
        try:
            conf = max(0.0, min(1.0, float(raw.get("confidence", 0.7))))
        except (TypeError, ValueError):
            conf = 0.7
        node = {"id": nid, "description": desc, "category": cat if cat in CATEGORIES else "other",
                "magnitude": mag if mag in MAGNITUDES else "moderate", "confidence": round(conf, 2),
                "depends_on": [], "note": _clean_text(raw.get("note", ""), 400),
                "included": bool(raw.get("included", True)), "added": bool(raw.get("added", False))}
        deps = raw.get("depends_on") or []
        node["_deps"] = deps if isinstance(deps, list) else []
        if isinstance(raw.get("deltas"), dict):
            node["deltas"] = {k: float(v) for k, v in raw["deltas"].items()
                              if isinstance(v, (int, float)) and k in DELTA_KEYS}
        if raw.get("rationale"):
            node["rationale"] = _clean_text(raw["rationale"], 300)
        out.append(node)
        if len(out) >= MAX_NODES:
            break
    ids = {n["id"] for n in out}
    for n in out:
        deps = []
        for d in n.pop("_deps"):
            try:
                d = int(d)
            except (TypeError, ValueError):
                continue
            if d in ids and d != n["id"] and d not in deps:
                deps.append(d)
        n["depends_on"] = deps
    _break_cycles(out)
    return out


def _break_cycles(nodes: List[dict]) -> None:
    by = {n["id"]: n for n in nodes}
    state: Dict[int, int] = {}

    def visit(i: int) -> None:
        state[i] = 1
        keep = []
        for d in by[i]["depends_on"]:
            if state.get(d) == 1:
                continue           # would close a cycle: drop this edge
            if state.get(d) is None:
                visit(d)
            keep.append(d)
        by[i]["depends_on"] = keep
        state[i] = 2

    for n in nodes:
        if state.get(n["id"]) is None:
            visit(n["id"])


def kept_chain(nodes: List[dict]) -> List[dict]:
    """The chain without excluded nodes. Anything that followed an excluded node now follows that node's own parents,
    and ids are renumbered 1..n in cause-before-effect order."""
    nodes = normalise_chain(nodes)
    by = {n["id"]: n for n in nodes}

    def live_parents(i: int, seen=None) -> List[int]:
        seen = seen or set()
        res: List[int] = []
        for d in by[i]["depends_on"]:
            if d in seen:
                continue
            seen.add(d)
            if by[d]["included"]:
                res.append(d)
            else:
                res.extend(live_parents(d, seen))
        return list(dict.fromkeys(res))

    keep = [n for n in nodes if n["included"]]
    deps = {n["id"]: live_parents(n["id"]) for n in keep}
    # topological order, ties broken by the original order
    order: List[int] = []
    pending = [n["id"] for n in keep]
    while pending:
        ready = [i for i in pending if all(d in order for d in deps[i])]
        if not ready:               # cannot happen after cycle-breaking, but never loop forever
            ready = [pending[0]]
        order.append(ready[0])
        pending.remove(ready[0])
    newid = {old: k + 1 for k, old in enumerate(order)}
    out = []
    for old in order:
        n = dict(by[old])
        n["id"] = newid[old]
        n["depends_on"] = sorted(newid[d] for d in deps[old] if d in newid)
        n["included"] = True
        out.append(n)
    return out


def to_mapper_nodes(chain: List[dict]) -> List[dict]:
    """The chain in the shape the older modules (causal_chains table, semantic mapper) store."""
    out = []
    for n in chain:
        d = {"node_id": n["id"], "description": n["description"], "magnitude": n["magnitude"], "category": n["category"],
             "depends_on": n["depends_on"], "confidence": n["confidence"]}
        if n.get("deltas"):
            d["deltas"] = n["deltas"]
        out.append(d)
    return out


def from_llm_chain(raw: List[dict]) -> List[dict]:
    """Groq's chain (node_id/description/...) as editable nodes."""
    return normalise_chain([{**r, "id": r.get("node_id")} for r in raw])


DELTA_KEYS = ("discretionary_spend_pct", "savings_rate_pct", "essential_cost_index_pct", "credit_availability_pct")


# ── the store ───────────────────────────────────────────────────────────────
class PropagationStore:
    def __init__(self, engine, lock):
        self.engine, self.lock = engine, lock
        metadata.create_all(engine)

    def get(self, key: str) -> Optional[dict]:
        with self.lock, self.engine.begin() as c:
            row = c.execute(select(propagation).where(propagation.c.key == key)).first()
        return _load(row) if row else None

    def list(self, kind: Optional[str] = None) -> List[dict]:
        q = select(propagation).where(propagation.c.status != "hidden").order_by(propagation.c.updated_at.desc())
        if kind:
            q = q.where(propagation.c.kind == kind)
        with self.lock, self.engine.begin() as c:
            rows = c.execute(q).fetchall()
        return [_load(r) for r in rows]

    def save(self, rec: dict) -> dict:
        now = time.time()
        rec["updated_at"] = now
        rec.setdefault("created_at", now)
        payload = json.dumps(rec, default=str)
        with self.lock, self.engine.begin() as c:
            row = c.execute(select(propagation.c.id).where(propagation.c.key == rec["key"])).first()
            vals = dict(kind=rec["kind"], title=rec.get("title", "")[:240], status=rec.get("status", "draft"),
                        data=payload, updated_at=now)
            if row is None:
                c.execute(insert(propagation).values(key=rec["key"], created_at=rec["created_at"], **vals))
            else:
                c.execute(update(propagation).where(propagation.c.id == row.id).values(**vals))
        return rec

    def patch(self, key: str, **fields) -> Optional[dict]:
        """Atomically merge fields into a stored record (used by the background job)."""
        with self.lock:
            rec = self.get_unlocked(key)
            if rec is None:
                return None
            rec.update(fields)
            now = time.time()
            rec["updated_at"] = now
            with self.engine.begin() as c:
                c.execute(update(propagation).where(propagation.c.key == key).values(
                    data=json.dumps(rec, default=str), status=rec.get("status", "draft"), updated_at=now,
                    title=rec.get("title", "")[:240]))
            return rec

    def all_keys(self) -> set:
        with self.lock, self.engine.begin() as c:
            return {r[0] for r in c.execute(select(propagation.c.key))}

    def delete(self, key: str) -> None:
        from sqlalchemy import delete as _delete
        with self.lock, self.engine.begin() as c:
            c.execute(_delete(propagation).where(propagation.c.key == key))

    def get_unlocked(self, key: str) -> Optional[dict]:
        with self.engine.begin() as c:
            row = c.execute(select(propagation).where(propagation.c.key == key)).first()
        return _load(row) if row else None


def _load(row) -> dict:
    try:
        rec = json.loads(row.data or "{}")
    except ValueError:
        rec = {}
    rec.setdefault("key", row.key)
    rec.setdefault("kind", row.kind)
    rec.setdefault("title", row.title or "")
    rec.setdefault("status", row.status or "draft")
    rec["created_at"], rec["updated_at"] = row.created_at, row.updated_at
    return rec


_store: Optional[PropagationStore] = None
_store_lock = threading.Lock()


def get_propagation_store() -> Optional[PropagationStore]:
    """Shares the database of the agents' experience (Postgres if reachable, else SQLite). None if neither works."""
    global _store
    with _store_lock:
        if _store is None:
            from town.experience import get_store
            base = get_store()
            if base is None:
                return None
            try:
                _store = PropagationStore(base.engine, base.lock)
            except Exception as e:
                logger.warning("Event propagation store unavailable: %s", e)
                return None
        return _store


def reset_for_tests() -> None:
    global _store
    _store = None


# ── presets as records ──────────────────────────────────────────────────────
def preset_record(preset_id: str) -> Optional[dict]:
    from town.scenarios import SCENARIOS
    from town.propagation_presets import PRESET_CHAINS
    from simulation.shock import describe
    sc = SCENARIOS.get(preset_id)
    spec = PRESET_CHAINS.get(preset_id)
    if sc is None or spec is None:
        return None
    return {
        "key": f"preset:{preset_id}", "kind": "preset", "preset_id": preset_id, "title": sc.title, "description": sc.blurb,
        "explain": spec["explain"], "watch": spec["watch"], "nodes": normalise_chain(spec["nodes"]),
        "shock": sc.shock.to_dict(), "shock_text": describe(sc.shock), "rules": sc.rules.describe(), "tags": sc.rules.tags(),
        "headlines": list(sc.headlines), "status": "ready", "job": {"state": "done", "message": ""},
        "brief": None, "editable": False, "clarifications": [],
    }


def preset_ids() -> List[str]:
    from town.scenarios import SCENARIO_ORDER
    return list(SCENARIO_ORDER)


# ── runs belonging to a record ──────────────────────────────────────────────
def runs_for(rec: dict, all_runs: List[dict]) -> List[dict]:
    """Saved runs (newest first) that were started from this scenario."""
    out = []
    for m in all_runs:
        src = m.get("source") or {}
        if rec["kind"] == "preset" and src.get("preset") == rec.get("preset_id"):
            out.append(m)
        elif rec["kind"] == "custom" and src.get("scenario_id") == rec.get("scenario_id"):
            out.append(m)
    keep = ("run_id", "status", "days", "days_done", "created_at", "finished_at", "town", "learning", "brain")
    return [{k: m.get(k) for k in keep} for m in sorted(out, key=lambda m: -(m.get("created_at") or 0))]


# ── shock preview ───────────────────────────────────────────────────────────
def shock_for_chain(nodes: List[dict]) -> dict:
    from simulation.shock import describe, shock_from_deltas
    chain = kept_chain(nodes)
    mapped = [{"deltas": n.get("deltas")} if n.get("deltas") else {} for n in chain]
    shock = shock_from_deltas(mapped)
    return {"shock": shock.to_dict(), "text": describe(shock), "nodes": len(chain),
            "quantified": sum(1 for n in chain if n.get("deltas")), "pending": sum(1 for n in chain if not n.get("deltas"))}


# ── the simulation brief (Groq, Ollama, then a template) ────────────────────
BRIEF_PROMPT = """You write the briefing that a town simulation will be run from. The town is a small Indian city with
twenty residents (daily-wage workers, shop owners, office staff, students, pensioners) whose money, food, fuel, jobs and
loans are simulated day by day. They learn about events through news and by talking to each other.

You are given the scenario and a chain of events the user has reviewed: each event, what it follows from, its size and
category. Use ONLY the events in the chain; do not add new causes or effects. Return JSON:
{
  "brief": "150 to 250 words, in plain prose: what happens, in what order, why each step follows, and who in a small
            Indian town feels it first and worst. Concrete, no hype.",
  "headlines": ["5 to 8 news headlines, in the order they reach the town, each under 22 words, specific and plausible,
                 each tied to a step of the chain; the first announces the triggering event"],
  "effects": ["4 to 6 short statements of what residents will actually experience (prices, jobs, credit, food, fuel)"]
}
Do not include any text outside the JSON object."""

BRIEF_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "simulation_brief",
        "schema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
                "headlines": {"type": "array", "items": {"type": "string"}},
                "effects": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["brief", "headlines", "effects"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _parse_brief(content: str) -> dict:
    d = json.loads(content)
    brief = _clean_text(d.get("brief", ""), 2200)
    heads = [_clean_text(h, 200) for h in d.get("headlines", []) if _clean_text(h, 200)][:MAX_HEADLINES]
    eff = [_clean_text(e, 200) for e in d.get("effects", []) if _clean_text(e, 200)][:6]
    if not brief or not heads:
        raise ValueError("empty brief")
    return {"brief": brief, "headlines": heads, "effects": eff}


def _chain_prompt(rec: dict, chain: List[dict]) -> str:
    lines = [f"Scenario: {rec.get('title', '')}"]
    if rec.get("description") and rec["description"] != rec.get("title"):
        lines.append(f"The user described it as: {rec['description']}")
    if rec.get("region"):
        lines.append(f"Region: {rec['region']}")
    if rec.get("time_horizon_months"):
        lines.append(f"Time horizon: {rec['time_horizon_months']} months")
    for c in rec.get("clarifications", []):
        if c.get("answer"):
            lines.append(f"The user clarified — {c.get('question', '')} {c['answer']}")
    lines.append("\nChain of events (reviewed by the user):")
    for n in chain:
        follows = f" (follows {', '.join('#%d' % d for d in n['depends_on'])})" if n["depends_on"] else " (the trigger)"
        lines.append(f"#{n['id']} [{n['magnitude']}, {n['category']}] {n['description']}{follows}")
    return "\n".join(lines)


def template_brief(rec: dict, chain: List[dict]) -> dict:
    """Used when no LLM answers: built straight from the chain, and labelled as such."""
    sentences = [n["description"].rstrip(".") for n in chain]
    brief = (f"{rec.get('title', 'The scenario')}. " + ". ".join(sentences[:10]) + ". "
             "Residents learn of these developments through the news and from each other, and respond according "
             "to their own money, food, fuel, jobs and loans.")
    return {"brief": brief, "headlines": [s for s in sentences[:MAX_HEADLINES]],
            "effects": [f"{n['description'].rstrip('.')}" for n in chain if n["magnitude"] == "major"][:6]}


def generate_brief(rec: dict, chain: List[dict]) -> dict:
    """Groq first (the same fallback ladder as the rest of the intake flow), then Ollama, then a template."""
    source = "template"
    result = None
    try:
        from app.services import llm
        result = llm._call_groq_with_fallback(
            system_prompt=BRIEF_PROMPT, user_content=_chain_prompt(rec, chain), response_format=BRIEF_SCHEMA,
            parse_fn=_parse_brief, ollama_fallback_fn=_ollama_brief, groq_api_key=os.getenv("GROQ_API_KEY"))
        if result is not None:
            source = "groq" if os.getenv("GROQ_API_KEY") else "ollama"
    except Exception as e:
        logger.warning("Simulation brief could not be written by an LLM: %s", e)
    if result is None:
        result = template_brief(rec, chain)
    result["source"] = source
    return result


def _ollama_brief(system_prompt: str, user_content: str) -> dict:
    import httpx
    from app.services import llm
    payload = {"model": llm.OLLAMA_MODEL, "stream": False, "format": "json",
               "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]}
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{llm.OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
    return _parse_brief(resp.json()["message"]["content"])


# ── background work ─────────────────────────────────────────────────────────
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="propagation")
_running: set = set()
_pending: Dict[str, bool] = {}          # key -> write the brief too, when the job now running is done
_running_lock = threading.Lock()


def start_job(key: str, brief: bool, runner=None) -> bool:
    """Quantify unquantified nodes (and, if asked, write the brief) in the background. False if one is already running."""
    with _running_lock:
        if key in _running:
            _pending[key] = _pending.get(key, False) or brief   # run again as soon as this one ends
            return False
        _running.add(key)
    _pool.submit(runner or _job, key, brief)
    return True


def job_running(key: str) -> bool:
    with _running_lock:
        return key in _running


def _map_node(node: dict) -> dict:
    from app.services.llm import map_node_to_deltas
    try:
        res = map_node_to_deltas(node={"node_id": node["id"], "description": node["description"], "magnitude": node["magnitude"],
                                       "category": node["category"], "confidence": node["confidence"]})
        deltas = {k: float(v) for k, v in res["deltas"].items() if k in DELTA_KEYS}
        return {"id": node["id"], "deltas": deltas, "rationale": str(res.get("rationale", ""))}
    except Exception as e:
        logger.warning("Quantifying node %s failed: %s", node.get("id"), e)
        return {"id": node["id"], "deltas": None, "rationale": ""}


def _job(key: str, brief: bool) -> None:
    store = get_propagation_store()
    try:
        if store is None:
            return
        rec = store.get(key)
        if rec is None:
            return
        # 1. numbers for nodes that don't have them
        todo = [n for n in rec["nodes"] if n.get("included", True) and not n.get("deltas")]
        if todo:
            store.patch(key, job={"state": "mapping", "message": f"Quantifying {len(todo)} events"})
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = {r["id"]: r for r in pool.map(_map_node, todo)}
            rec = store.get(key)
            merged = []
            for n in rec["nodes"]:
                r = results.get(n["id"])
                if r and r["deltas"] is not None and not n.get("deltas"):
                    n = {**n, "deltas": r["deltas"], "rationale": r["rationale"]}
                merged.append(n)
            rec = store.patch(key, nodes=merged)
        # 2. the brief
        if brief:
            store.patch(key, job={"state": "writing", "message": "Writing the simulation brief"})
            rec = store.get(key)
            chain = kept_chain(rec["nodes"])
            out = generate_brief(rec, chain)
            rec = store.patch(key, brief=out, headlines=out["headlines"])
            _persist_chain_row(rec)
            store.patch(key, status="ready", job={"state": "done", "message": ""},
                        shock=shock_for_chain(rec["nodes"])["shock"], finalized_at=time.time())
        else:
            store.patch(key, job={"state": "idle", "message": ""})
    except Exception as e:   # never leave a record stuck in 'working'
        logger.exception("Propagation job for %s failed", key)
        if store is not None:
            store.patch(key, status="failed" if brief else "draft", job={"state": "failed", "message": str(e)[:200]})
    finally:
        with _running_lock:
            _running.discard(key)
            again = _pending.pop(key, None)
        if again is not None:
            start_job(key, again)


def _persist_chain_row(rec: dict) -> Optional[int]:
    """Write the kept chain (with numbers) to the older causal_chains table, so every older module sees what the user kept."""
    if rec.get("kind") != "custom" or not rec.get("scenario_id"):
        return None
    try:
        from db.session import SessionLocal
        from models.causal_chains import CausalChain
        db = SessionLocal()
        try:
            row = CausalChain(scenario_id=rec["scenario_id"], chain=to_mapper_nodes(kept_chain(rec["nodes"])))
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not write the causal_chains row: %s", e)
        return None


def headlines_for(scenario_id: int) -> Optional[List[str]]:
    """The news timeline written for this scenario's brief, if there is one (used when a run starts)."""
    store = get_propagation_store()
    rec = store.get(f"custom:{scenario_id}") if store else None
    if rec and rec.get("brief") and rec["brief"].get("headlines"):
        return list(rec["brief"]["headlines"])[:MAX_HEADLINES]
    return None


def import_legacy(store: PropagationStore) -> int:
    """Scenarios made before this page existed (a scenarios row plus a causal chain) get a record too, once."""
    try:
        from db.session import SessionLocal
        from models.causal_chains import CausalChain
        from models.scenarios import Scenario
    except Exception:
        return 0
    have = store.all_keys()
    added = 0
    db = SessionLocal()
    try:
        for sc in db.query(Scenario).order_by(Scenario.id).all():
            key = f"custom:{sc.id}"
            if key in have:
                continue
            row = db.query(CausalChain).filter(CausalChain.scenario_id == sc.id).order_by(CausalChain.id.desc()).first()
            if row is None or not row.chain:
                continue
            nodes = from_llm_chain(list(row.chain))
            if not nodes:
                continue
            ts = sc.created_at.timestamp() if getattr(sc, "created_at", None) else time.time()
            store.save({"key": key, "kind": "custom", "scenario_id": sc.id, "title": sc.name or f"Scenario {sc.id}",
                        "description": sc.description or sc.name or "", "clarifications": [], "nodes": nodes,
                        "status": "ready", "job": {"state": "idle", "message": ""}, "brief": None, "headlines": [],
                        "legacy": True, "created_at": ts})
            added += 1
    except Exception as e:
        logger.warning("Importing earlier scenarios failed: %s", e)
    finally:
        db.close()
    return added
