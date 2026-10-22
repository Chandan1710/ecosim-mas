"""
runs.py — start, stream, save and replay town runs (used by the API).

Every run is saved as two files in backend/runs/:
  <run_id>.jsonl      every event, one per line (the replayable log)
  <run_id>.meta.json  title, settings, status and final stats (for the run list)
After a run finishes, the LLM writes a short story for each agent and for the
town from the log; those go in <run_id>.stories.json and feed the PDF reports.

Only one live run at a time: all runs share the same free-tier API keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional, Set

from simulation.shock import Shock, describe
from town.scenarios import HEADLINES, SCENARIOS, TITLES, Rules

logger = logging.getLogger(__name__)

RUNS_DIR = os.getenv("ECOSIM_RUNS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs")

PRESET_TITLES = TITLES
PRESET_HEADLINES = HEADLINES


def scenario_from_db(scenario_id: int):
    """(shock, headlines, title) for a scenario created through the intake flow."""
    from simulation.shock import shock_from_deltas
    from db.session import SessionLocal
    from models.scenarios import Scenario
    from models.causal_chains import CausalChain
    from app.api.endpoints.simulate import _ensure_mapped_chain
    db = SessionLocal()
    try:
        sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if sc is None:
            raise LookupError(f"Scenario {scenario_id} not found")
        title = sc.name or f"Scenario {scenario_id}"
        rec = (db.query(CausalChain).filter(CausalChain.scenario_id == scenario_id)
               .order_by(CausalChain.id.desc()).first())
    finally:
        db.close()
    if rec is None:
        raise LookupError(f"Scenario {scenario_id} has no causal chain yet")
    nodes = _ensure_mapped_chain(rec.id)
    heads = [title] + [n.get("description", "") for n in nodes[:7] if n.get("description")]
    try:   # the news timeline Groq wrote from the chain the user kept, if there is one
        from town.propagation import headlines_for
        heads = headlines_for(scenario_id) or heads
    except Exception:
        pass
    return shock_from_deltas(nodes), heads, title


def _path(run_id: str, ext: str) -> str:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    return os.path.join(RUNS_DIR, f"{safe}.{ext}")


def read_meta(run_id: str) -> Optional[dict]:
    try:
        with open(_path(run_id, "meta.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_meta(meta: dict) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    tmp = _path(meta["run_id"], "meta.json.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=1, default=str)
    os.replace(tmp, _path(meta["run_id"], "meta.json"))


def read_events(run_id: str) -> List[dict]:
    out = []
    try:
        with open(_path(run_id, "jsonl")) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass   # a half-written last line from an interrupted run
    except OSError:
        pass
    return out


def read_stories(run_id: str) -> dict:
    try:
        with open(_path(run_id, "stories.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@dataclass
class LiveRun:
    run_id: str
    meta: dict
    events: List[dict] = field(default_factory=list)
    queues: Set[asyncio.Queue] = field(default_factory=set)
    task: Optional[asyncio.Task] = None
    sim: object = None
    done: bool = False


class RunManager:
    def __init__(self):
        self.live: Dict[str, LiveRun] = {}

    # ── queries ─────────────────────────────────────────────────────────────
    def active(self) -> Optional[LiveRun]:
        return next((lr for lr in self.live.values() if not lr.done), None)

    def list_runs(self) -> List[dict]:
        if not os.path.isdir(RUNS_DIR):
            return []
        metas = []
        for name in os.listdir(RUNS_DIR):
            if name.endswith(".meta.json"):
                m = read_meta(name[: -len(".meta.json")])
                if m:
                    metas.append(self._fresh(m))
        return sorted(metas, key=lambda m: m.get("created_at", 0), reverse=True)

    def get_meta(self, run_id: str) -> Optional[dict]:
        lr = self.live.get(run_id)
        if lr is not None:
            return dict(lr.meta)
        m = read_meta(run_id)
        return self._fresh(m) if m else None

    def _fresh(self, m: dict) -> dict:
        if m.get("status") == "running" and m["run_id"] not in self.live:
            m = {**m, "status": "interrupted"}     # the server stopped mid-run
        return m

    def events(self, run_id: str) -> List[dict]:
        lr = self.live.get(run_id)
        return list(lr.events) if lr is not None else read_events(run_id)

    # ── starting ────────────────────────────────────────────────────────────
    def resolve(self, preset: Optional[str], scenario_id: Optional[int]):
        if scenario_id is not None:
            shock, heads, title = scenario_from_db(scenario_id)
            return shock, heads, title, {"scenario_id": scenario_id}
        preset = preset or "severe"
        if preset not in SCENARIOS:
            raise ValueError(f"Unknown preset '{preset}'. Use one of: {', '.join(SCENARIOS)}")
        sc = SCENARIOS[preset]
        return sc.shock, list(sc.headlines), sc.title, {"preset": preset}

    @staticmethod
    def rules_for(source: dict) -> Rules:
        """Extra scenario rules (lockdown, rationing, ...) for a preset run; none for your own scenarios."""
        sc = SCENARIOS.get((source or {}).get("preset", ""))
        return sc.rules if sc else Rules()

    async def start(self, *, shock: Shock, headlines: List[str], title: str, source: dict, days: int = 10,
                    pace: str = "fast", seed: int = 7, n_agents: int = 20, brain_kind: str = "auto",
                    memory_pref: str = "auto", brain=None, rules: Optional[Rules] = None,
                    learning: str = "off") -> dict:
        from town.engine import TownSimulation, make_brain
        from town.memory import make_memory

        if self.active() is not None:
            raise RuntimeError(f"Run {self.active().run_id} is still going; stop it first or wait for it to finish")
        from town.memory import get_embedder
        brain = brain or make_brain(brain_kind)
        await asyncio.get_running_loop().run_in_executor(None, get_embedder)   # first load can take seconds
        store = None
        if learning in ("learn", "frozen"):
            from town.experience import get_store
            store = await asyncio.get_running_loop().run_in_executor(None, get_store)
            if store is None:   # no database reachable: run without learning rather than fail
                learning = "off"
        src = source or {}
        scenario_id = str(src.get("preset") or (f"custom-{src['scenario_id']}" if src.get("scenario_id") else "custom"))
        sim = TownSimulation(shock=shock, headlines=headlines, n_agents=n_agents, seed=seed, days=days,
                             brain=brain, memory=None, title=title, pace=pace, rules=rules,
                             learning=learning, scenario_id=scenario_id, store=store)
        sim.memory = await asyncio.get_running_loop().run_in_executor(None, make_memory, sim.run_id, memory_pref)
        meta = {
            "run_id": sim.run_id, "title": title, "source": source, "days": days, "pace": sim.pace,
            "seed": seed, "n_agents": n_agents, "shock": shock.to_dict(), "shock_text": describe(shock),
            "rules": sim.econ.rules.describe(), "learning": sim.learner.mode,
            "brain": brain.kind, "providers": getattr(getattr(brain, "pool", None), "describe", lambda: "")(),
            "memory": sim.memory.backend, "status": "running", "created_at": time.time(),
            "finished_at": None, "days_done": 0, "stats": None, "town": None, "error": None, "stories": None,
        }
        os.makedirs(RUNS_DIR, exist_ok=True)
        write_meta(meta)
        lr = LiveRun(sim.run_id, meta, sim=sim)
        self.live[sim.run_id] = lr
        lr.task = asyncio.create_task(self._drive(lr))
        return dict(meta)

    async def _drive(self, lr: LiveRun) -> None:
        sim = lr.sim
        status, err = "done", None
        try:
            with open(_path(lr.run_id, "jsonl"), "w") as f:
                async for ev in sim.run():
                    f.write(json.dumps(ev, default=str) + "\n")
                    f.flush()
                    self._publish(lr, ev)
                    if ev["type"] == "run_end" and ev.get("learning"):
                        lr.meta["learning_summary"] = ev["learning"]
                    if ev["type"] == "day_end":
                        lr.meta["days_done"] = ev["day"]
                        lr.meta["town"] = ev["town"]
                        write_meta(lr.meta)
        except asyncio.CancelledError:
            status = "stopped"
        except Exception as e:   # keep the server alive; record what went wrong
            logger.exception("Town run %s failed", lr.run_id)
            status, err = "failed", str(e)[:300]
        lr.meta.update(status=status, error=err, finished_at=time.time(), stats=dict(sim.stats))
        write_meta(lr.meta)
        lr.done = True
        self._publish(lr, None)
        pool = getattr(sim.brain, "pool", None)
        if status == "done" and pool is not None and pool.available:
            lr.meta["stories"] = "writing"
            write_meta(lr.meta)
            try:
                from town.analysis import write_stories
                await write_stories(lr.run_id, lr.events, lr.meta, pool)
                lr.meta["stories"] = "ready"
            except Exception:
                logger.exception("Could not write stories for %s", lr.run_id)
                lr.meta["stories"] = "failed"
            write_meta(lr.meta)
        if pool is not None:
            await pool.close()

    def _publish(self, lr: LiveRun, ev: Optional[dict]) -> None:
        if ev is not None:
            lr.events.append(ev)
        for q in list(lr.queues):
            q.put_nowait(ev)

    async def stop(self, run_id: str) -> bool:
        lr = self.live.get(run_id)
        if lr is None or lr.done or lr.task is None:
            return False
        lr.task.cancel()
        try:
            await lr.task
        except asyncio.CancelledError:
            pass
        return True

    # ── streaming ───────────────────────────────────────────────────────────
    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        """Everything so far, then live events until the run ends."""
        lr = self.live.get(run_id)
        if lr is None:
            for ev in read_events(run_id):
                yield ev
            return
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(lr.events)          # no await between copy and register: nothing is missed
        live = not lr.done
        if live:
            lr.queues.add(q)
        try:
            for ev in backlog:
                yield ev
            if not live:
                return
            # events that arrived while the backlog was being sent are waiting in the queue
            while True:
                ev = await q.get()
                if ev is None:
                    return
                yield ev
        finally:
            lr.queues.discard(q)


manager = RunManager()
