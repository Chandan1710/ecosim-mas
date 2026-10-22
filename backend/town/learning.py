"""
learning.py — how the town's agents learn from what happens to them (no weight updates).

Every simulated day each agent gets a REWARD: food on the table, medicine, bills paid, debt, a cash buffer
and a job. Good days feel like a small reward, hunger, missed payments and job loss like punishment. The
experience (situation → plan → outcome → reward) is stored in a database, and when a month ends each agent
distils LESSONS from it ("when petrol spikes, buy groceries first"). Lessons carry a strength that grows each
time experience confirms them and shrinks if they were followed and things still went badly.

Other people matter too. When a conversation is followed by a changed plan, the agent notes whether the
change turned out well or badly and adjusts how much it TRUSTS that person's advice.

In the next simulation each agent's prompt contains its strongest relevant lessons, similar past days and who
it trusts, so it can change its decisions. The same loop runs inside a month: today's reward shapes tomorrow.

Modes (per run):
  off     fresh agents: no memory of earlier runs, nothing is recorded (rewards are still measured)
  learn   use what was learned and record this run
  frozen  use what was learned but record nothing (a fair test of what training achieved)

Reward values are documented in reward_for(); they are deliberately simple and inspectable.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from town.experience import ExperienceStore

logger = logging.getLogger(__name__)

MODES = ("off", "learn", "frozen")
REWARD_MIN, REWARD_MAX = -3.0, 1.0
TRUST_STEP = 0.2
CONTEXT_LESSONS = 4
CONTEXT_CHARS = 1700
CATEGORY_DISCRETIONARY = ("eating out", "shopping", "entertainment")


def agent_key(seed: int, agent) -> str:
    """The same resident in the same town keeps one identity across runs."""
    slug = re.sub(r"[^a-z0-9]+", "-", agent.name.lower()).strip("-")
    return f"s{seed}-{agent.id}-{slug}"


# ── reward ──────────────────────────────────────────────────────────────────
def reward_for(agent, prev: dict, snap: dict, outs: List[dict]) -> Tuple[float, Dict[str, float]]:
    """One day's reward for one agent, with the parts that make it.

    food     -1.0 went hungry, -0.25 almost out of food, +0.1 well stocked
    health   -0.8 out of medicine they need
    bills    -0.4 per missed payment, -1.5 per default, +0.05 per bill paid (max +0.15)
    debt     -0.3 per moneylender loan, and up to ±0.3 for debt rising or falling (relative to income)
    savings  +0.1 with 2+ weeks of cash runway, -0.1 under a week, -0.3 under 3 days
    job      -2.0 the day a job is lost, -0.15 a day without work (not for pensioners / allowance)
    fuel     -0.1 a day with an empty tank when they depend on it
    The total is clipped to [-3, +1].
    """
    parts: Dict[str, float] = {}
    food = 0.0
    if agent.daily_grocery_need > 0:
        if snap["days_hungry"] > prev["days_hungry"]:
            food = -1.0
        elif snap["pantry_days"] < 1.5:
            food = -0.25
        elif snap["pantry_days"] >= 4:
            food = 0.1
    parts["food"] = food
    parts["health"] = -0.8 if agent.chronic_condition and snap["medicine_days"] <= 0 else 0.0
    bills, paid = 0.0, 0
    for o in outs:
        d = o.get("data") or {}
        if d.get("default"):
            bills -= 1.5
        elif d.get("bill") and not o.get("ok"):
            bills -= 0.4
        elif d.get("bill") and o.get("ok"):
            paid += 1
    parts["bills"] = bills + min(0.15, 0.05 * paid)
    monthly = max(1000.0, agent.monthly_income_estimate)
    debt = sum(-0.3 for o in outs if o.get("ok") and str(o.get("text", "")).startswith("Borrowed") and "moneylender" in str(o.get("text", "")))
    debt += max(-0.3, min(0.3, -0.5 * (snap["debt"] - prev["debt"]) / monthly))
    parts["debt"] = debt
    runway = snap["money"] / max(1.0, monthly / 30.0)
    parts["savings"] = 0.1 if runway >= 14 else (-0.3 if runway < 3 else (-0.1 if runway < 7 else 0.0))
    if prev["employed"] and not snap["employed"]:
        job = -2.0
    elif not snap["employed"] and agent.pay_type not in ("pension", "allowance"):
        job = -0.15
    else:
        job = 0.0
    parts["job"] = job
    parts["fuel"] = -0.1 if agent.fuel_litres_per_day > 0 and snap["fuel_days"] <= 0 else 0.0
    total = max(REWARD_MIN, min(REWARD_MAX, sum(parts.values())))
    return round(total, 3), {k: round(v, 3) for k, v in parts.items() if abs(v) > 1e-9}


def mood(r: float) -> str:
    return "very bad" if r <= -1.0 else "bad" if r <= -0.3 else "fine" if r < 0.15 else "good"


# ── plan helpers ────────────────────────────────────────────────────────────
def plan_text(plan: dict) -> str:
    from town.world import PLACES
    bits = []
    for ph in ("morning", "afternoon", "evening"):
        s = plan.get(ph) or {}
        if not s:
            continue
        place = PLACES.get(s.get("place"))
        name = place.name if place else s.get("place", "?")
        bits.append(f"{ph}: {s.get('do', 'rest')} at {name}" + (f" (₹{s['spend']:,.0f})" if s.get("spend") else ""))
    m = plan.get("money") or {}
    if m.get("borrow_moneylender"):
        bits.append(f"borrowed ₹{m['borrow_moneylender']:,.0f} from the moneylender")
    if m.get("borrow_bank"):
        bits.append(f"asked the bank for ₹{m['borrow_bank']:,.0f}")
    if m.get("skip"):
        bits.append("skipped " + ", ".join(m["skip"]))
    return "; ".join(bits)


def plan_signature(plan: dict) -> tuple:
    sig = []
    for ph in ("morning", "afternoon", "evening"):
        s = plan.get(ph) or {}
        sig.append((s.get("place"), s.get("do"), float(s.get("spend") or 0) > 0))
    m = plan.get("money") or {}
    sig.append((bool(m.get("borrow_bank")), bool(m.get("borrow_moneylender")), len(m.get("skip") or []), bool(m.get("send_home"))))
    return tuple(sig)


def signature_diff(old: tuple, new: tuple) -> str:
    from town.world import PLACES
    out = []
    for i, ph in enumerate(("morning", "afternoon", "evening")):
        if old[i] != new[i]:
            p, do, sp = new[i]
            out.append(f"{ph}: {do} at {PLACES[p].name if p in PLACES else p}")
    if old[3] != new[3]:
        out.append("changed how I handle borrowing, skipped payments or sending money home")
    return "; ".join(out[:2]) or "changed the plan"


def situation_features(agent, econ) -> dict:
    bills = sum(b["amount"] for b in econ.bills_due(agent, 7))
    return {"money": round(agent.money), "food_days": round(agent.pantry_days, 1), "fuel_days": round(agent.fuel_days, 1),
            "medicine_days": round(agent.medicine_days), "debt": round(sum(l.outstanding for l in agent.loans)),
            "bills_7d": round(bills), "employed": agent.employed, "grocery_price": round(econ.price_multiplier("groceries"), 2),
            "lockdown": econ.lockdown_active(), "rationed": econ.ration_factor("groceries") < 0.95,
            "runway_days": round(agent.money / max(1.0, agent.monthly_income_estimate / 30.0), 1)}


@dataclass
class Learned:
    """What an agent carries into a decision from earlier experience."""
    text: str = ""
    hints: Dict[str, float] = field(default_factory=dict)
    used: List[str] = field(default_factory=list)       # lesson keys shown
    shown: List[str] = field(default_factory=list)      # short texts shown (for the UI)


@dataclass
class _Rec:
    day: int
    state: dict
    plan: dict
    outcomes: List[dict] = field(default_factory=list)
    reward: float = 0.0
    parts: dict = field(default_factory=dict)


class Learner:
    def __init__(self, mode: str, store: Optional[ExperienceStore], run_id: str, seed: int, scenario_id: str,
                 scenario_title: str, onset_day: int, embedder=None):
        self.mode = mode if (mode in MODES and (store is not None or mode == "off")) else "off"
        self.store = store if self.mode != "off" else None
        self.run_id, self.seed = run_id, seed
        self.scenario_id, self.scenario_title = scenario_id or "", scenario_title or ""
        self.onset_day = onset_day
        self.embedder = embedder
        self.keys: Dict[str, str] = {}
        self.names: Dict[str, str] = {}
        self.lessons: Dict[str, List[dict]] = {}
        self.lesson_vecs: Dict[str, np.ndarray] = {}
        self.trust: Dict[str, Dict[str, dict]] = {}
        self.history: Dict[str, List[dict]] = {}
        self.prior_runs: Dict[str, List[dict]] = {}
        self.recs: Dict[str, List[_Rec]] = {}
        self.cur: Dict[str, _Rec] = {}
        self.used_keys: Dict[str, set] = {}
        self.talks: List[dict] = []              # conversations, waiting to see if they changed a decision
        self.finished: List[dict] = []           # influences with their outcome
        self.prev_snap: Dict[str, dict] = {}
        self.prev_sig: Dict[str, tuple] = {}
        self.last_day_sig: Dict[str, Dict[int, tuple]] = {}
        self.error = ""

    # ── lifecycle ───────────────────────────────────────────────────────────
    @property
    def reading(self) -> bool:
        return self.mode in ("learn", "frozen")

    @property
    def writing(self) -> bool:
        return self.mode == "learn"

    def begin(self, agents: Dict[str, Any], snapshots: Dict[str, dict]) -> dict:
        for aid, a in agents.items():
            self.keys[aid] = agent_key(self.seed, a)
            self.names[aid] = a.name
            self.recs[aid] = []
            self.used_keys[aid] = set()
            self.last_day_sig[aid] = {}
        self.prev_snap = {aid: dict(s) for aid, s in snapshots.items()}
        info = {"mode": self.mode, "prior_runs": {}, "lessons": {}}
        if self.reading:
            try:
                for aid, key in self.keys.items():
                    self.lessons[aid] = self.store.lessons_for(key)
                    self.trust[aid] = self.store.trust_for(key)
                    self.history[aid] = self.store.history_for(key, 120)
                    self.prior_runs[aid] = self.store.runs_for(key)
                    info["prior_runs"][aid] = len(self.prior_runs[aid])
                    info["lessons"][aid] = len(self.lessons[aid])
                    self._embed_lessons(aid)
            except Exception as e:   # database trouble must never stop a simulation
                logger.warning("Learning disabled for this run: %s", e)
                self.error = str(e)
                self.mode, self.store = "off", None
                info["mode"] = "off"
                info["error"] = self.error
        return info

    def _embed(self, texts: List[str]) -> np.ndarray:
        if self.embedder is None:
            from town.memory import HashEmbedder
            self.embedder = HashEmbedder()
        return self.embedder.encode(texts)

    def _embed_lessons(self, aid: str) -> None:
        ls = self.lessons.get(aid) or []
        if ls:
            vecs = self._embed([l["text"] for l in ls])
            self.lesson_vecs[aid] = vecs

    # ── before a decision ───────────────────────────────────────────────────
    def context(self, agent, econ, notes: List[str], agents: Dict[str, Any]) -> Learned:
        aid = agent.id
        out = Learned()
        if not self.reading:
            return out
        ls = self.lessons.get(aid) or []
        lines: List[str] = []
        if ls:
            query = " ".join([self.scenario_title] + list(econ.news.get(econ.day, [])) + notes[-4:] + [agent.job_title])
            qv = self._embed([query])[0]
            vecs = self.lesson_vecs.get(aid)
            scored = []
            for i, l in enumerate(ls):
                rel = float(np.dot(vecs[i], qv)) if vecs is not None and len(vecs) > i else 0.0
                same = 0.4 if l["scenario_id"] == self.scenario_id and self.scenario_id else (0.12 if not l["scenario_id"] else 0.0)
                scored.append((0.5 * max(0.0, rel) + 0.9 * l["strength"] + same, l))
            scored.sort(key=lambda t: -t[0])
            chosen = [l for s, l in scored[:CONTEXT_LESSONS] if l["strength"] >= 0.2]
            for l in chosen:
                tag = "do" if l["kind"] == "do" else "avoid"
                sure = "very sure" if l["strength"] >= 0.7 else "fairly sure" if l["strength"] >= 0.45 else "not certain"
                lines.append(f"- [{tag}] {l['text']} ({sure}; confirmed {l['confirmed']}×)")
                out.used.append(l["key"])
                out.shown.append(l["text"])
                w = l["strength"] * (1.0 if l["scenario_id"] == self.scenario_id else 0.6)
                for hk, hv in (l.get("hint") or {}).items():
                    out.hints[hk] = max(out.hints.get(hk, 0.0), float(hv) * w)
            self.used_keys[aid].update(out.used)
        text = ""
        if lines:
            text += "WHAT YOU HAVE LEARNED FROM EARLIER MONTHS (these really happened to you; use them)\n" + "\n".join(lines)
        past = self._similar_days(agent, econ)
        if past:
            text += ("\n\n" if text else "") + "SIMILAR DAYS YOU REMEMBER\n" + "\n".join(past)
        tr = self._trust_lines(aid, agents)
        if tr:
            text += ("\n\n" if text else "") + "WHOSE ADVICE YOU TRUST\n" + "\n".join(tr)
        out.text = text[:CONTEXT_CHARS]
        return out

    def _similar_days(self, agent, econ) -> List[str]:
        hist = self.history.get(agent.id) or []
        if not hist:
            return []
        now = situation_features(agent, econ)
        scored = []
        for h in hist:
            st = h.get("state") or {}
            sim = 0.0
            sim += 0.6 if h["scenario_id"] == self.scenario_id and self.scenario_id else 0.0
            sim += 0.4 if (st.get("food_days", 9) < 2) == (now["food_days"] < 2) else 0.0
            sim += 0.3 if bool(st.get("lockdown")) == now["lockdown"] else 0.0
            sim += 0.3 if (st.get("bills_7d", 0) > st.get("money", 0)) == (now["bills_7d"] > now["money"]) else 0.0
            if h["run_id"] == self.run_id and now["lockdown"] != bool(st.get("lockdown")):
                sim -= 0.2
            scored.append((sim + 0.8 * abs(h["reward"]), h))
        scored.sort(key=lambda t: -t[0])
        lines = []
        seen = set()
        for s, h in scored:
            if len(lines) >= 2 or abs(h["reward"]) < 0.25:
                break
            sig = (h["run_id"], h["day"])
            if sig in seen:
                continue
            seen.add(sig)
            when = "earlier this month" if h["run_id"] == self.run_id else f"in an earlier month ({h['scenario_title'] or 'another scenario'})"
            st = h.get("state") or {}
            did = plan_text(h.get("action") or {}) or "stayed home"
            what = "; ".join((h.get("outcome") or [])[:2])
            lines.append(f"- Day {h['day']} {when}: food {st.get('food_days', '?')} days, ₹{st.get('money', 0):,} cash. I {did}. "
                         f"{what} Reward {h['reward']:+.1f} ({mood(h['reward'])}).")
        return lines

    def _trust_lines(self, aid: str, agents: Dict[str, Any]) -> List[str]:
        tr = self.trust.get(aid) or {}
        by_key = {self.keys[i]: i for i in self.keys}
        good = sorted([(v["trust"], k, v) for k, v in tr.items() if v["trust"] >= 0.62 and k in by_key], reverse=True)[:2]
        bad = sorted([(v["trust"], k, v) for k, v in tr.items() if v["trust"] <= 0.38 and k in by_key])[:2]
        lines = []
        for _, k, v in good:
            lines.append(f"- You trust {v['name']}: their advice has worked out for you ({v['helped']} of {v['n']} times)")
        for _, k, v in bad:
            lines.append(f"- You are wary of {v['name']}'s advice: acting on it went badly ({v['hurt']} of {v['n']} times)")
        return lines

    # ── during the day ──────────────────────────────────────────────────────
    def log_plan(self, agent, econ, plan: dict) -> None:
        aid = agent.id
        rec = _Rec(day=econ.day, state=situation_features(agent, econ), plan=_copy_plan(plan))
        self.cur[aid] = rec
        sig = plan_signature(plan)
        self.last_day_sig[aid][econ.day] = sig

    def update_plan(self, aid: str, plan: dict) -> None:
        """The plan as actually carried out (a lockdown can overrule parts of it)."""
        if aid in self.cur:
            self.cur[aid].plan = _copy_plan(plan)

    def log_outcome(self, aid: str, phase: str, out, kind: str) -> None:
        rec = self.cur.get(aid)
        if rec is not None and out.text:
            rec.outcomes.append({"text": out.text, "ok": out.ok, "importance": out.importance, "amount": out.amount,
                                 "data": dict(out.data or {}), "phase": phase, "kind": kind})

    def log_talk(self, day: int, a_id: str, b_id: str, topic: str, learned: Dict[str, str]) -> None:
        for x, other in ((a_id, b_id), (b_id, a_id)):
            self.talks.append({"agent": x, "other": other, "day": day, "topic": topic, "learned": learned.get(x, "")})

    # ── end of day ──────────────────────────────────────────────────────────
    def end_of_day(self, day: int, agents: Dict[str, Any], snapshots: Dict[str, dict], title: str) -> Dict[str, dict]:
        rewards: Dict[str, dict] = {}
        rows = []
        for aid, a in agents.items():
            rec = self.cur.get(aid)
            outs = rec.outcomes if rec else []
            total, parts = reward_for(a, self.prev_snap[aid], snapshots[aid], outs)
            rewards[aid] = {"total": total, "parts": parts}
            if rec is not None:
                rec.reward, rec.parts = total, parts
                self.recs[aid].append(rec)
                texts = [o["text"] for o in sorted(outs, key=lambda o: -o["importance"])[:3]]
                row = {"agent_key": self.keys[aid], "run_id": self.run_id, "scenario_id": self.scenario_id,
                       "scenario_title": self.scenario_title, "day": day, "state": rec.state, "action": _public_plan(rec.plan),
                       "outcome": texts, "reward": total, "parts": parts}
                rows.append(row)
                if self.writing:
                    self.history.setdefault(aid, []).insert(0, {
                        "run_id": self.run_id, "scenario_id": self.scenario_id, "scenario_title": self.scenario_title, "day": day,
                        "state": rec.state, "action": _public_plan(rec.plan), "outcome": texts, "reward": total, "parts": parts})
        self.prev_snap = {aid: dict(s) for aid, s in snapshots.items()}
        self._settle_talks(day, agents, rewards)
        if self.writing and rows:
            try:
                self.store.add_experience(rows)
            except Exception as e:
                self._fail(e)
        return rewards

    def _settle_talks(self, day: int, agents: Dict[str, Any], rewards: Dict[str, dict]) -> None:
        """A conversation yesterday + a different plan today + today's reward = was that advice any good?"""
        pending = [t for t in self.talks if t["day"] == day - 1]
        self.talks = [t for t in self.talks if t["day"] >= day]    # today's talks wait for tomorrow
        for t in pending:
            aid, oid = t["agent"], t["other"]
            if aid not in agents or oid not in agents:
                continue
            old, new = self.last_day_sig.get(aid, {}).get(day - 1), self.last_day_sig.get(aid, {}).get(day)
            changed = old is not None and new is not None and old != new
            rec = {"agent_key": self.keys[aid], "other_key": self.keys[oid], "run_id": self.run_id, "day": day - 1,
                   "topic": t["topic"], "learned": t["learned"], "changed": changed if old is not None and new is not None else None,
                   "change_desc": signature_diff(old, new) if changed else "", "next_reward": rewards[aid]["total"] if changed else None,
                   "agent": aid, "other": oid}
            self.finished.append(rec)
            if not changed or not self.writing:
                continue
            past = [r.reward for r in self.recs.get(aid, []) if r.day < day]
            baseline = float(np.mean(past)) if past else 0.0
            delta = TRUST_STEP * max(-1.0, min(1.0, rewards[aid]["total"] - baseline))
            if abs(delta) < 0.02:
                continue
            try:
                tr = self.store.update_trust(self.keys[aid], self.keys[oid], self.names[oid], delta, delta > 0,
                                             t["learned"] or t["topic"] or "")
                self.trust.setdefault(aid, {})[self.keys[oid]] = {"name": self.names[oid], "trust": tr, "topic": t["topic"],
                    "n": self.trust.get(aid, {}).get(self.keys[oid], {}).get("n", 0) + 1,
                    "helped": self.trust.get(aid, {}).get(self.keys[oid], {}).get("helped", 0) + (1 if delta > 0 else 0),
                    "hurt": self.trust.get(aid, {}).get(self.keys[oid], {}).get("hurt", 0) + (1 if delta < 0 else 0)}
            except Exception as e:
                self._fail(e)

    def _fail(self, e: Exception) -> None:
        logger.warning("Saving what the agents learned failed: %s", e)
        self.error = str(e)
        self.mode, self.store = "off", None

    # ── end of run ──────────────────────────────────────────────────────────
    async def finish(self, brain, agents: Dict[str, Any], econ, headlines: List[str]) -> Tuple[dict, dict]:
        """Distil lessons, save them, and report. Returns (per-agent lessons for the UI, run summary)."""
        import asyncio
        per_agent: Dict[str, List[dict]] = {}
        summary: Dict[str, Any] = {"mode": self.mode, "scenario_id": self.scenario_id}
        means = {}
        for aid in agents:
            rs = [r.reward for r in self.recs.get(aid, [])]
            means[aid] = float(np.mean(rs)) if rs else 0.0
        summary["mean_reward"] = round(float(np.mean(list(means.values()))) if means else 0.0, 3)
        summary["agent_means"] = {aid: round(v, 3) for aid, v in means.items()}
        if self.mode != "learn":
            return per_agent, summary

        prev_means: List[float] = []
        cands_by_agent: Dict[str, List[dict]] = {}
        for aid, a in agents.items():
            infl = [i for i in self.finished if i["agent"] == aid]
            cands_by_agent[aid] = detect_lessons(a, self.recs.get(aid, []), self.scenario_id, self.scenario_title,
                                                 self.onset_day, infl, agents, self.keys)
            prior = [r["mean_reward"] for r in self.prior_runs.get(aid, [])]
            if prior:
                prev_means.append(float(np.mean(prior)))

        async def refine(aid: str):
            cands = cands_by_agent[aid]
            if not cands or getattr(brain, "kind", "") != "llm" or not hasattr(brain, "distil"):
                return aid, None
            try:
                return aid, await brain.distil(agents[aid], self.scenario_title, headlines, self.recs.get(aid, []), cands)
            except Exception as e:   # LLM trouble: the rule-based lessons still stand
                logger.info("Lesson wording by the LLM failed for %s: %s", aid, e)
                return aid, None

        refined = dict(await asyncio.gather(*[refine(aid) for aid in agents]))
        total_new = 0
        for aid, a in agents.items():
            items = cands_by_agent[aid]
            llm_items = refined.get(aid) or []
            covered = {}
            extra = []
            for l in llm_items:
                idxs = [i for i in l.get("based_on", []) if 1 <= i <= len(items)]
                if idxs:
                    base = items[idxs[0] - 1]
                    covered[base["key"]] = {"text": l["text"], "kind": l["kind"]}
                else:
                    extra.append({"key": "llm:" + re.sub(r"[^a-z0-9]+", "-", l["text"].lower())[:50], "text": l["text"],
                                  "kind": l["kind"], "strength": 0.4, "scenario_id": self.scenario_id, "hint": {}, "source": "llm"})
            final = []
            for c in items:
                c = dict(c)
                if c["key"] in covered:
                    c.update(covered[c["key"]], source="llm")
                final.append(c)
            final += extra
            try:
                have = {l["key"] for l in (self.lessons.get(aid) or [])}
                self.store.upsert_lessons(self.keys[aid], final, self.run_id)
                # lessons that were in use: stronger if the month went better than before, weaker if not
                # lessons in use: judged on whether this month beat the same agent's earlier month of the same kind
                same = [r["mean_reward"] for r in self.prior_runs.get(aid, []) if r["scenario_id"] == self.scenario_id]
                ref = float(np.mean(same)) if same else float(np.mean([r["mean_reward"] for r in self.prior_runs.get(aid, [])] or [-0.3]))
                step = max(-0.3, min(0.1, 0.4 * (means[aid] - ref)))
                self.store.adjust_lessons(self.keys[aid], sorted(self.used_keys.get(aid, set())), step)
                if self.finished:
                    self.store.add_influence([{k: v for k, v in i.items() if k not in ("agent", "other")}
                                              for i in self.finished if i["agent"] == aid])
            except Exception as e:
                self._fail(e)
                break
            per_agent[aid] = [{"text": c["text"], "kind": c["kind"], "strength": round(c["strength"], 2), "new": c["key"] not in have}
                              for c in sorted(final, key=lambda c: -c["strength"])[:3]]
            total_new += sum(1 for c in final if c["key"] not in have)
        summary["lessons_new"] = total_new
        if prev_means:
            summary["previous_mean_reward"] = round(float(np.mean(prev_means)), 3)
        try:
            summary["lessons_total"] = self.store.counts()["town_lessons"] if self.store else 0
        except Exception:
            pass
        if self.error:
            summary["error"] = self.error
        return per_agent, summary


# ── lessons from a month of records ─────────────────────────────────────────
def _short(title: str) -> str:
    return title if len(title) <= 38 else title[:36].rstrip() + "…"


def detect_lessons(agent, recs: List[_Rec], scenario_id: str, title: str, onset: int, influences: List[dict],
                   agents: Dict[str, Any], keys: Dict[str, str]) -> List[dict]:
    """Rule-based lessons: what went wrong or right this month, in the agent's own words."""
    out: List[dict] = []
    if not recs:
        return out
    sc = scenario_id or "any"
    t = _short(title or "that month")

    def add(key, kind, text, strength, hint=None):
        out.append({"key": f"{key}:{sc}", "kind": kind, "text": text, "strength": round(max(0.1, min(0.95, strength)), 2),
                    "scenario_id": scenario_id, "hint": hint or {}, "source": "rule"})

    def texts(r):
        return " ".join(o["text"].lower() for o in r.outcomes)

    hungry = [r for r in recs if r.parts.get("food", 0) <= -1.0]
    low_food = [r for r in recs if r.state.get("food_days", 9) < 1.5 and r.state.get("food_days", 9) >= 0]
    if hungry or len(low_food) >= 2:
        d = (hungry or low_food)[0].day
        why = " Shops were rationing, so I had to buy a little every day." if any(r.state.get("rationed") for r in recs) else ""
        add("food", "do", f"In '{t}' the food at home ran out around day {d}. Next time I will buy groceries as soon as prices start "
            f"rising or a shortage or lockdown is announced, and keep at least a week of food at home.{why}",
            0.45 + 0.15 * len(hungry), {"stock_food": 1})

    ml = [r for r in recs if "moneylender" in texts(r) and any(o["text"].startswith("Borrowed") for o in r.outcomes)]
    if ml:
        later = [x.reward for x in recs if x.day > ml[0].day]
        before = [x.reward for x in recs if x.day <= ml[0].day]
        worse = later and before and np.mean(later) < np.mean(before) - 0.05
        penalised = any("missed" in texts(x) or "defaulted" in texts(x) for x in recs if x.day > ml[0].day)
        if worse or penalised:
            add("moneylender", "avoid", f"In '{t}' I borrowed from the moneylender on day {ml[0].day} and the 8% a week made my money "
                "problems worse. I will not borrow from the moneylender for anything except food or medicine, and I will cut other spending first.",
                0.5 + (0.2 if penalised else 0.0), {"avoid_moneylender": 1})

    missed = [r for r in recs if r.parts.get("bills", 0) <= -0.4]
    if missed:
        add("bills", "do", f"In '{t}' I missed payments on day {missed[0].day} and my credit score suffered. I will pay rent and EMIs "
            "first and keep enough cash for the next week's bills before spending on anything else.",
            0.4 + 0.1 * len(missed), {"bill_buffer": 1})

    lost = [r for r in recs if r.parts.get("job", 0) <= -2.0]
    if lost:
        add("job", "do", f"In '{t}' I lost my job on day {lost[0].day}. When news of layoffs or a slowdown appears I will build a cash "
            "buffer of two months of expenses early and cut non-essential spending.", 0.6, {"cut_discretionary": 1, "bill_buffer": 1})

    empty = [r for r in recs if any("out of fuel" in o["text"].lower() or "fuel tank is empty" in o["text"].lower() for o in r.outcomes)]
    if empty and agent.fuel_litres_per_day > 0:
        add("fuel", "do", f"In '{t}' I ran out of fuel on day {empty[0].day} and lost work or paid for the bus. I will refuel when I am "
            "down to two days of fuel, especially when petrol prices are rising.", 0.5, {"refuel_early": 1})

    discretionary = [r for r in recs if r.day >= onset and any(
        o["text"].startswith("Bought") and any(c in o["text"].lower() for c in CATEGORY_DISCRETIONARY) and o["ok"] for o in r.outcomes)]
    trouble = [r for r in recs if r.parts.get("food", 0) <= -1 or r.parts.get("bills", 0) <= -0.4 or r.parts.get("savings", 0) <= -0.3]
    if discretionary and trouble and discretionary[0].day <= trouble[-1].day:
        add("discretionary", "avoid", f"In '{t}' I kept spending on eating out and shopping while the shock was hitting, and then struggled to "
            "pay for food and bills. When prices rise or work dries up I will cut treats first.", 0.45, {"cut_discretionary": 1})

    blocked = [r for r in recs if any("allowed to go" in o["text"].lower() or "lockdown" in o["text"].lower() and not o["ok"] for o in r.outcomes)]
    if len(blocked) >= 2 and (hungry or low_food):
        add("lockdown", "do", "A lockdown meant I could not go out and my food ran low. As soon as a lockdown is announced I will buy a "
            "week of food and medicine that same day, before the shops queue up.", 0.65, {"stock_food": 1})

    ranked = sorted(recs, key=lambda r: r.reward)
    worst, best = ranked[0], ranked[-1]
    if worst.reward <= -0.8:
        what = (sorted(worst.outcomes, key=lambda o: -o["importance"])[0]["text"] if worst.outcomes else "things went wrong")
        add("worst", "avoid", f"Day {worst.day} of '{t}' went very badly: {what.rstrip('.')}. My plan that day was: "
            f"{plan_text(worst.plan) or 'stay home'}. I should not repeat that.", min(0.8, 0.3 + abs(worst.reward) * 0.2))
    if best.reward >= 0.2 and best.day > onset and any(
            best.plan.get(ph, {}).get("do") == "shop" and best.plan.get(ph, {}).get("spend") for ph in ("morning", "afternoon", "evening")):
        add("best", "do", f"Day {best.day} of '{t}' went well. My plan that day was: {plan_text(best.plan) or 'stay home'}. "
            "That is worth repeating in a similar situation.", 0.35)

    # people: whose advice turned out useful
    by_other: Dict[str, List[dict]] = {}
    for i in influences:
        if i.get("changed"):
            by_other.setdefault(i["other"], []).append(i)
    base = float(np.mean([r.reward for r in recs])) if recs else 0.0
    for oid, items in by_other.items():
        rs = [i["next_reward"] for i in items if i.get("next_reward") is not None]
        if len(rs) < 2 or oid not in agents:     # one coincidence is not evidence
            continue
        diff = float(np.mean(rs)) - base
        who = agents[oid].name
        topic = (items[-1].get("learned") or items[-1].get("topic") or "money and prices")[:90]
        if diff >= 0.25:
            add(f"adviser-{keys[oid]}", "do", f"{who}'s advice helped me ({topic}). I should listen to {who} when things get hard.",
                min(0.8, 0.3 + diff))
        elif diff <= -0.3:
            add(f"adviser-{keys[oid]}", "avoid", f"Acting on {who}'s advice ({topic}) went badly for me. I should double-check what {who} says "
                "before changing my plans.", min(0.8, 0.3 + abs(diff)))
    return out


def _copy_plan(plan: dict) -> dict:
    import copy
    return copy.deepcopy({k: plan[k] for k in ("morning", "afternoon", "evening", "money", "talk_to") if k in plan})


def _public_plan(plan: dict) -> dict:
    return {k: v for k, v in plan.items() if k in ("morning", "afternoon", "evening", "money", "talk_to")}


# ── what the app shows ──────────────────────────────────────────────────────
def learning_summary(store: ExperienceStore, agents: List[Any], seed: int) -> dict:
    """Per-agent view for the Agent profiles page."""
    out: Dict[str, Any] = {"backend": store.backend, "counts": store.counts(), "agents": {}}
    names = {agent_key(seed, a): a.name for a in agents}
    for a in agents:
        key = agent_key(seed, a)
        ls = sorted(store.lessons_for(key), key=lambda l: -l["strength"])
        tr = store.trust_for(key)
        out["agents"][a.id] = {
            "runs": [{"run_id": r["run_id"], "scenario": r["scenario_title"], "mean_reward": round(r["mean_reward"], 2),
                      "days": r["days"], "at": r["at"]} for r in store.runs_for(key)],
            "lessons": [{"text": l["text"], "kind": l["kind"], "strength": round(l["strength"], 2), "confirmed": l["confirmed"],
                         "scenario_id": l["scenario_id"], "source": l["source"]} for l in ls[:8]],
            "lesson_count": len(ls),
            "trust": sorted([{"name": v["name"] or names.get(k, k), "trust": round(v["trust"], 2), "helped": v["helped"], "hurt": v["hurt"],
                              "topic": v["topic"]} for k, v in tr.items() if abs(v["trust"] - 0.5) >= 0.1],
                           key=lambda x: -abs(x["trust"] - 0.5))[:5],
            "influences": [{"name": names.get(i["other_key"], i["other_key"]), "day": i["day"], "topic": i["topic"],
                            "changed": i["changed"], "change": i["change_desc"], "reward": i["next_reward"]}
                           for i in store.influences_for(key, 5)],
        }
    return out
