"""
experience.py — the database where the town's agents keep what they have learned.

Four small tables, all prefixed `town_`:

  town_experience   one row per agent per simulated day: the situation, the plan, what happened,
                    and the reward (food, health, bills, debt, savings, job)
  town_lessons      what the agent concluded, in words, with how sure they are (strength), how
                    often experience confirmed it, and an optional machine-readable hint
  town_social       how far an agent trusts each person they know (updated when acting on that
                    person's advice went well or badly)
  town_influence    every time a conversation was followed by a changed decision, and what
                    happened next

Where it lives (first that works):
  1. ECOSIM_EXPERIENCE_DB             any SQLAlchemy URL you choose
  2. the project's PostgreSQL         (DATABASE_URL, the same server as scenarios and causal chains)
  3. runs/experience.db               a SQLite file, no setup, always available

A failure to reach the database never stops a simulation: learning is switched off for that run
and the reason is logged.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine, delete,
                        func, insert, select, text, update)
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

RUNS_DIR = os.getenv("ECOSIM_RUNS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs")
MAX_LESSONS_PER_AGENT = 40

metadata = MetaData()

experience = Table(
    "town_experience", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agent_key", String(96), nullable=False, index=True),
    Column("run_id", String(32), nullable=False, index=True),
    Column("scenario_id", String(40)),
    Column("scenario_title", String(160)),
    Column("day", Integer, nullable=False),
    Column("state", Text),       # JSON: the situation when the plan was made
    Column("action", Text),      # JSON: the plan
    Column("outcome", Text),     # JSON: what happened (texts)
    Column("reward", Float, nullable=False),
    Column("parts", Text),       # JSON: reward by component
    Column("created_at", Float, nullable=False),
)

lessons = Table(
    "town_lessons", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agent_key", String(96), nullable=False, index=True),
    Column("key", String(120), nullable=False),
    Column("text", Text, nullable=False),
    Column("kind", String(8), nullable=False),          # do | avoid
    Column("scenario_id", String(40)),
    Column("strength", Float, nullable=False),          # 0..1, how sure
    Column("confirmed", Integer, nullable=False, default=1),   # times experience agreed
    Column("hint", Text),                               # JSON, e.g. {"stock_food": 1}
    Column("source", String(8), nullable=False),        # rule | llm
    Column("first_run", String(32)),
    Column("last_run", String(32)),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("agent_key", "key", name="uq_town_lessons_agent_key"),
)

social = Table(
    "town_social", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agent_key", String(96), nullable=False, index=True),
    Column("other_key", String(96), nullable=False),
    Column("other_name", String(96)),
    Column("trust", Float, nullable=False),             # 0..1, starts at 0.5
    Column("n", Integer, nullable=False, default=0),    # times their advice changed a decision
    Column("helped", Integer, nullable=False, default=0),
    Column("hurt", Integer, nullable=False, default=0),
    Column("last_topic", Text),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("agent_key", "other_key", name="uq_town_social_pair"),
)

influence = Table(
    "town_influence", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agent_key", String(96), nullable=False, index=True),
    Column("other_key", String(96), nullable=False),
    Column("run_id", String(32), nullable=False),
    Column("day", Integer, nullable=False),
    Column("topic", Text),
    Column("learned", Text),
    Column("changed", Integer),                         # 1 changed the next plan, 0 did not, NULL unknown
    Column("change_desc", Text),
    Column("next_reward", Float),
    Column("created_at", Float, nullable=False),
)


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _l(s: Optional[str], default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def _sqlite_url() -> str:
    os.makedirs(RUNS_DIR, exist_ok=True)
    return "sqlite:///" + os.path.abspath(os.path.join(RUNS_DIR, "experience.db"))


def _open(url: str) -> Engine:
    kw: Dict[str, Any] = {}
    if url.startswith("postgresql"):
        kw["connect_args"] = {"connect_timeout": 3}
    elif url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, pool_pre_ping=True, **kw)
    with eng.begin() as c:
        c.execute(text("SELECT 1"))
    metadata.create_all(eng)
    return eng


class ExperienceStore:
    """Thin wrapper over the four tables. Every method is safe to call from a single event loop."""

    def __init__(self, url: Optional[str] = None):
        self.error = ""
        engine = None
        tried = []
        candidates = [url] if url else []
        if not url:
            if os.getenv("ECOSIM_EXPERIENCE_DB"):
                candidates.append(os.environ["ECOSIM_EXPERIENCE_DB"])
            else:
                try:
                    from db.session import SQLALCHEMY_DATABASE_URL
                    candidates.append(SQLALCHEMY_DATABASE_URL)
                except Exception as e:   # no project database module / driver
                    tried.append(f"project database unavailable ({type(e).__name__})")
                candidates.append(_sqlite_url())
        for u in candidates:
            try:
                engine = _open(u)
                self.url = u
                break
            except Exception as e:
                tried.append(f"{u.split('@')[-1]}: {type(e).__name__}")
                logger.info("Experience DB %s not usable: %s", u.split('@')[-1], e)
        if engine is None:
            raise RuntimeError("no experience database available: " + "; ".join(tried))
        self.engine = engine
        self.backend = engine.dialect.name          # postgresql | sqlite
        self.lock = threading.Lock()
        logger.info("Agent experience is stored in %s", self.backend)

    # ── writing ─────────────────────────────────────────────────────────────
    def add_experience(self, rows: List[dict]) -> None:
        if not rows:
            return
        now = time.time()
        recs = [{"agent_key": r["agent_key"], "run_id": r["run_id"], "scenario_id": r.get("scenario_id", ""),
                 "scenario_title": r.get("scenario_title", ""), "day": r["day"], "state": _j(r.get("state", {})),
                 "action": _j(r.get("action", {})), "outcome": _j(r.get("outcome", [])), "reward": float(r["reward"]),
                 "parts": _j(r.get("parts", {})), "created_at": now} for r in rows]
        with self.lock, self.engine.begin() as c:
            c.execute(insert(experience), recs)

    def upsert_lessons(self, agent_key: str, items: List[dict], run_id: str) -> None:
        """New lessons are added; one that experience confirms again gets stronger."""
        now = time.time()
        with self.lock, self.engine.begin() as c:
            have = {r.key: r for r in c.execute(select(lessons).where(lessons.c.agent_key == agent_key))}
            for it in items:
                row = have.get(it["key"])
                if row is None:
                    c.execute(insert(lessons).values(
                        agent_key=agent_key, key=it["key"], text=it["text"], kind=it["kind"], scenario_id=it.get("scenario_id", ""),
                        strength=float(it["strength"]), confirmed=1, hint=_j(it.get("hint") or {}), source=it.get("source", "rule"),
                        first_run=run_id, last_run=run_id, created_at=now, updated_at=now))
                else:
                    stronger = min(1.0, row.strength + 0.15 + 0.1 * float(it["strength"]))
                    c.execute(update(lessons).where(lessons.c.id == row.id).values(
                        text=it["text"], strength=stronger, confirmed=row.confirmed + 1, last_run=run_id, updated_at=now,
                        hint=_j(it.get("hint") or _l(row.hint, {})), source=it.get("source", row.source)))
            # keep each agent's notebook short: forget the weakest
            rows = list(c.execute(select(lessons.c.id, lessons.c.strength).where(lessons.c.agent_key == agent_key)
                                  .order_by(lessons.c.strength.desc(), lessons.c.updated_at.desc())))
            for r in rows[MAX_LESSONS_PER_AGENT:]:
                c.execute(delete(lessons).where(lessons.c.id == r.id))

    def adjust_lessons(self, agent_key: str, keys: List[str], delta: float) -> None:
        """Lessons that were in use during a run get a little stronger if the run went well, weaker if not."""
        if not keys or not delta:
            return
        with self.lock, self.engine.begin() as c:
            for k in keys:
                c.execute(update(lessons).where((lessons.c.agent_key == agent_key) & (lessons.c.key == k)).values(
                    strength=func.max(0.05, func.min(1.0, lessons.c.strength + delta))))

    def update_trust(self, agent_key: str, other_key: str, other_name: str, delta: float, helped: bool, topic: str) -> float:
        now = time.time()
        with self.lock, self.engine.begin() as c:
            row = c.execute(select(social).where((social.c.agent_key == agent_key) & (social.c.other_key == other_key))).first()
            if row is None:
                trust = max(0.0, min(1.0, 0.5 + delta))
                c.execute(insert(social).values(agent_key=agent_key, other_key=other_key, other_name=other_name, trust=trust, n=1,
                                                helped=int(helped), hurt=int(not helped), last_topic=topic[:300], updated_at=now))
            else:
                trust = max(0.0, min(1.0, row.trust + delta))
                c.execute(update(social).where(social.c.id == row.id).values(
                    trust=trust, n=row.n + 1, helped=row.helped + int(helped), hurt=row.hurt + int(not helped),
                    last_topic=topic[:300], updated_at=now, other_name=other_name))
        return trust

    def add_influence(self, rows: List[dict]) -> None:
        if not rows:
            return
        now = time.time()
        recs = [{"agent_key": r["agent_key"], "other_key": r["other_key"], "run_id": r["run_id"], "day": r["day"],
                 "topic": r.get("topic", ""), "learned": r.get("learned", ""),
                 "changed": None if r.get("changed") is None else int(bool(r["changed"])),
                 "change_desc": r.get("change_desc", ""), "next_reward": r.get("next_reward"), "created_at": now} for r in rows]
        with self.lock, self.engine.begin() as c:
            c.execute(insert(influence), recs)

    # ── reading ─────────────────────────────────────────────────────────────
    def lessons_for(self, agent_key: str) -> List[dict]:
        with self.lock, self.engine.begin() as c:
            rows = c.execute(select(lessons).where(lessons.c.agent_key == agent_key)).fetchall()
        return [{"key": r.key, "text": r.text, "kind": r.kind, "scenario_id": r.scenario_id or "", "strength": r.strength,
                 "confirmed": r.confirmed, "hint": _l(r.hint, {}), "source": r.source, "updated_at": r.updated_at} for r in rows]

    def trust_for(self, agent_key: str) -> Dict[str, dict]:
        with self.lock, self.engine.begin() as c:
            rows = c.execute(select(social).where(social.c.agent_key == agent_key)).fetchall()
        return {r.other_key: {"name": r.other_name, "trust": r.trust, "n": r.n, "helped": r.helped, "hurt": r.hurt,
                              "topic": r.last_topic or ""} for r in rows}

    def history_for(self, agent_key: str, limit: int = 200) -> List[dict]:
        with self.lock, self.engine.begin() as c:
            rows = c.execute(select(experience).where(experience.c.agent_key == agent_key)
                             .order_by(experience.c.created_at.desc(), experience.c.day.desc()).limit(limit)).fetchall()
        return [{"run_id": r.run_id, "scenario_id": r.scenario_id or "", "scenario_title": r.scenario_title or "", "day": r.day,
                 "state": _l(r.state, {}), "action": _l(r.action, {}), "outcome": _l(r.outcome, []), "reward": r.reward,
                 "parts": _l(r.parts, {})} for r in rows]

    def runs_for(self, agent_key: str) -> List[dict]:
        """Reward per run, oldest first: the learning curve."""
        with self.lock, self.engine.begin() as c:
            rows = c.execute(select(experience.c.run_id, experience.c.scenario_id, experience.c.scenario_title,
                                    func.avg(experience.c.reward), func.sum(experience.c.reward), func.count(),
                                    func.min(experience.c.created_at))
                             .where(experience.c.agent_key == agent_key)
                             .group_by(experience.c.run_id, experience.c.scenario_id, experience.c.scenario_title)
                             .order_by(func.min(experience.c.created_at))).fetchall()
        return [{"run_id": r[0], "scenario_id": r[1] or "", "scenario_title": r[2] or "", "mean_reward": float(r[3]),
                 "total_reward": float(r[4]), "days": int(r[5]), "at": float(r[6])} for r in rows]

    def influences_for(self, agent_key: str, limit: int = 12) -> List[dict]:
        with self.lock, self.engine.begin() as c:
            rows = c.execute(select(influence).where(influence.c.agent_key == agent_key)
                             .order_by(influence.c.created_at.desc()).limit(limit)).fetchall()
        return [{"other_key": r.other_key, "run_id": r.run_id, "day": r.day, "topic": r.topic or "", "learned": r.learned or "",
                 "changed": None if r.changed is None else bool(r.changed), "change_desc": r.change_desc or "",
                 "next_reward": r.next_reward} for r in rows]

    def counts(self) -> Dict[str, int]:
        with self.lock, self.engine.begin() as c:
            return {t.name: int(c.execute(select(func.count()).select_from(t)).scalar() or 0)
                    for t in (experience, lessons, social, influence)}

    def reset(self, agent_key: Optional[str] = None) -> None:
        """Forget everything (or everything about one resident)."""
        with self.lock, self.engine.begin() as c:
            for t in (influence, social, lessons, experience):
                c.execute(delete(t).where(t.c.agent_key == agent_key) if agent_key else delete(t))


_store: Optional[ExperienceStore] = None
_store_error = ""


def get_store(url: Optional[str] = None, refresh: bool = False) -> Optional[ExperienceStore]:
    """The shared store, or None if no database can be reached (the reason is in last_error())."""
    global _store, _store_error
    if url is not None or refresh:
        _store = None
    if _store is None:
        try:
            _store = ExperienceStore(url)
            _store_error = ""
        except Exception as e:
            _store_error = str(e)
            logger.warning("Agent learning unavailable: %s", e)
            return None
    return _store


def last_error() -> str:
    return _store_error
