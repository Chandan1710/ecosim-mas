"""
engine.py — runs the town day by day and emits an event stream.

Each simulated day:
  1. morning: income arrives, news is read (by agents who follow news),
     job cuts may be announced; each agent collects what is new to it
  2. think: every agent with something new to consider asks its brain for a
     plan (in parallel); agents with nothing new follow their routine
  3. three phases (morning, afternoon, evening): agents walk to the places
     they chose and act there; agents who meet may talk, and what they hear
     becomes memory
  4. night: money moves (moneylender, sending money home, repayments), shops
     close their books, bills are auto-debited, food/fuel/medicine are used up
  5. agents with enough new experience reflect and form beliefs

Everything that happens is an event (see EVENT TYPES below). The same events
drive the live WebSocket, the saved run log, the dashboard and the report.

EVENT TYPES
  run_start   {run_id, brain, providers, agents:[public profile], map, shock, headlines}
  day_start   {day, weekday, prices, fuel_price, news}
  decision    {day, agent, mode: llm|routine|mock|fallback, provider, thought, plan, fixes}
  move        {day, phase, agent, from, to}
  action      {day, phase, agent, ok, text, importance, amount, kind}
  conversation{day, phase, place, a, b, dialogue, learned:{a,b}, provider}
  reflection  {day, agent, insights, provider}
  day_end     {day, agents:{id: snapshot}, town:{...}}
  run_end     {days, usage, totals}
"""

from __future__ import annotations

import asyncio
import copy
import logging
import random
import uuid
from typing import AsyncIterator, Dict, List, Optional, Tuple

from simulation.shock import Shock
from town.scenarios import Rules
from town.brain import LLMBrain, MockBrain, category_for, normalise_decision
from town.economy import Outcome, TownEconomy
from town.learning import Learned, Learner
from town.llm_pool import LLMUnavailable
from town.memory import LocalMemory, MemoryStore
from town.population import Agent, generate_population
from town.world import PHASES, PLACES, map_json

logger = logging.getLogger(__name__)

SOCIAL_PLACES = {"park", "market", "cafe", "restaurant", "mall", "auto_stand", "kirana"}
RETHINK_EVERY = 3           # agents re-plan at least every N days even if nothing changed
REFLECT_THRESHOLD = 60      # summed importance of new memories that triggers reflection
MIN_DAYS_BETWEEN_REFLECTIONS = 6
# pace -> (day the shock starts, days until it is at full strength)
#   normal: two calm days, then the shock builds over 8 days (job cuts on day 10) — for 30-day runs
#   fast:   one calm day, full strength by day 5 (job cuts on day 5) — for short demo runs
PACES = {"normal": (3, 8), "fast": (2, 4)}


class TownSimulation:
    def __init__(self, shock: Optional[Shock] = None, headlines: Optional[List[str]] = None,
                 n_agents: int = 20, seed: int = 7, days: int = 30, brain=None,
                 memory: Optional[MemoryStore] = None, run_id: Optional[str] = None,
                 max_talks_per_phase: int = 3, title: str = "", pace: str = "normal",
                 rules: Optional[Rules] = None, learning: str = "off", scenario_id: str = "", store=None):
        self.seed = seed
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.shock = shock or Shock()
        self.headlines = headlines or []
        self.title = title
        self.days = days
        self.rng = random.Random(seed)
        self.agents: Dict[str, Agent] = {a.id: a for a in generate_population(n_agents, seed)}
        self.pace = pace if pace in PACES else "normal"
        onset, ramp = PACES[self.pace]
        self.econ = TownEconomy(self.shock, seed=seed, headlines=self.headlines, days=days,
                                onset_day=onset, ramp_days=ramp, rules=rules)
        self.brain = brain or MockBrain(seed)
        self.memory = memory or LocalMemory(self.run_id)
        self.max_talks_per_phase = max_talks_per_phase
        self.events: List[dict] = []
        self.pending_notes: Dict[str, List[Tuple[str, int]]] = {aid: [] for aid in self.agents}
        self.carry_notes: Dict[str, List[Tuple[str, int]]] = {aid: [] for aid in self.agents}  # yesterday, for today's prompt
        self.last_plan: Dict[str, dict] = {}
        self.last_think_day: Dict[str, int] = {}
        self.last_reflect_day: Dict[str, int] = {aid: 0 for aid in self.agents}
        self.seen_prices: Dict[str, Dict[str, Tuple[float, int]]] = {aid: {} for aid in self.agents}
        self._restrictions_yesterday = self.econ.restrictions_today()
        self.learner = Learner(learning, store, self.run_id, seed, scenario_id, title, self.econ.layoff_day)
        self.stats = {"llm_decisions": 0, "routine": 0, "fallbacks": 0, "conversations": 0, "reflections": 0}

    # ── helpers ─────────────────────────────────────────────────────────────
    def _emit(self, ev: dict) -> dict:
        ev = {"run_id": self.run_id, **ev}
        self.events.append(ev)
        return ev

    def _note(self, aid: str, text: str, importance: int) -> None:
        if text and all(t != text for t, _ in self.pending_notes[aid]):   # same thing twice in a day = one memory
            self.pending_notes[aid].append((text, importance))

    def _remember_outcome(self, aid: str, phase: str, out: Outcome, kind: str = "action") -> Optional[dict]:
        if not out.text:
            return None
        self._note(aid, out.text, out.importance)
        self.learner.log_outcome(aid, phase, out, kind)
        return {"type": "action", "day": self.econ.day, "phase": phase, "agent": aid, "ok": out.ok,
                "text": out.text, "importance": out.importance, "amount": round(out.amount, 2), "kind": kind}

    def _snapshot(self, a: Agent) -> dict:
        return {"money": round(a.money, 0), "pantry_days": round(a.pantry_days, 1), "fuel_days": round(a.fuel_days, 1),
                "medicine_days": round(a.medicine_days, 1), "credit_score": a.credit_score, "employed": a.employed,
                "khata_due": round(a.khata_due, 0), "defaulted": a.is_defaulted, "location": a.location,
                "debt": round(sum(l.outstanding for l in a.loans), 0), "days_hungry": a.days_hungry,
                "earned": round(a.earned, 0), "spent": {k: round(v, 0) for k, v in a.spent.items()}}

    def _town_stats(self) -> dict:
        ag = list(self.agents.values())
        return {
            "avg_money": round(sum(a.money for a in ag) / len(ag), 0),
            "hungry_today": sum(1 for a in ag if a.pantry_days <= 0 and a.daily_grocery_need > 0),
            "low_food": sum(1 for a in ag if a.daily_grocery_need > 0 and a.pantry_days < 2),
            "defaulted": sum(1 for a in ag if a.is_defaulted),
            "unemployed": sum(1 for a in ag if not a.employed and a.pay_type not in ("pension", "allowance")),
            "moneylender_borrowers": sum(1 for a in ag if any(l.lender == "moneylender" for l in a.loans)),
            "prices": self.econ.price_board(),
            "shop_sales": {k: v[-1] for k, v in self.econ.sales_history.items() if v},
        }

    # ── the run ─────────────────────────────────────────────────────────────
    async def run(self) -> AsyncIterator[dict]:
        learning = self.learner.begin(self.agents, {a.id: self._snapshot(a) for a in self.agents.values()})
        yield self._emit({
            "type": "run_start", "title": self.title, "brain": self.brain.kind,
            "providers": getattr(getattr(self.brain, "pool", None), "describe", lambda: "")(),
            "memory_backend": self.memory.backend, "days": self.days, "shock": self.shock.to_dict(),
            "pace": self.pace, "shock_onset_day": self.econ.onset_day, "shock_full_day": self.econ.layoff_day,
            "headlines": self.headlines, "rules": self.econ.rules.describe(), "map": map_json(), "learning": learning,
            "agents": [a.public_state() for a in self.agents.values()],
        })
        seed_items = [(a.id, 0, "evening", "observation",
                       f"Prices in town have been steady for months; my household spends about "
                       f"₹{a.daily_grocery_need:,.0f} a day on groceries.", 2) for a in self.agents.values()]
        self.memory.add_many(seed_items)
        for d in range(1, self.days + 1):
            async for ev in self._run_day():
                yield ev
            self.econ.advance()
        lessons, learning = await self.learner.finish(self.brain, self.agents, self.econ, self.headlines)
        if lessons:
            yield self._emit({"type": "lessons", "agents": lessons})
        pool = getattr(self.brain, "pool", None)
        yield self._emit({"type": "run_end", "days": self.days, "usage": pool.usage() if pool else [],
                          "totals": self.stats, "town": self._town_stats(), "learning": learning})

    async def _run_day(self) -> AsyncIterator[dict]:
        econ = self.econ
        day = econ.day
        for a in self.agents.values():
            a.location = a.home
        # 1. morning
        for a in self.agents.values():
            for out in econ.morning_income(a):
                self._note(a.id, out.text, out.importance)
        for a, where in econ.maybe_layoffs(self.agents):
            self._note(a.id, f"Lost my job: {where} is cutting staff", 10)
        losses = econ.disaster_losses(self.agents)
        if econ.lockdown_active() and not econ.lockdown_active(day - 1):
            for a in self.agents.values():
                self._note(a.id, "A strict lockdown has begun: we must all stay at home except for essentials", 9)
        news = list(econ.news.get(day, []))
        for a in self.agents.values():
            if a.reads_news:
                for h in news:
                    self._note(a.id, f"Read in the news: {h}", 6)
        yield self._emit({"type": "day_start", "day": day, "weekday": econ.weekday(), "prices": econ.price_board(),
                          "closed": sorted(p.id for p in PLACES.values() if p.kind != "home" and not econ.place_open(p)),
                          "fuel_price": econ.fuel_price(), "news": news,
                          "news_readers": [a.id for a in self.agents.values() if a.reads_news] if news else []})
        for a, out in losses:
            ev = self._remember_outcome(a.id, "morning", out)
            if ev:
                yield self._emit(ev)

        # this morning's notes become memories; yesterday's were stored last night
        self.memory.add_many([(aid, day, "morning", "news" if t.startswith("Read in the news") else "observation", t, imp)
                              for aid, notes in self.pending_notes.items() for t, imp in notes])
        todays: Dict[str, List[str]] = {}
        max_imp: Dict[str, int] = {}
        for aid in self.agents:
            notes = self.carry_notes[aid] + self.pending_notes[aid]
            todays[aid] = [t for t, _ in sorted(notes, key=lambda n: -n[1])[:10]]
            max_imp[aid] = max([imp for _, imp in notes], default=0)
        self.pending_notes = {aid: [] for aid in self.agents}
        self.carry_notes = {aid: [] for aid in self.agents}

        # 2. think
        plans: Dict[str, dict] = {}
        tasks = []
        for a in self.agents.values():
            if self._needs_thinking(a, max_imp[a.id]):
                tasks.append(self._think(a, todays[a.id]))
            else:
                plan = self._routine_plan(a)
                plans[a.id] = plan
                self.learner.log_plan(a, econ, plan)
                self.stats["routine"] += 1
                yield self._emit({"type": "decision", "day": day, "agent": a.id, "mode": "routine", "provider": "",
                                  "thought": plan["thought"], "plan": self._plan_public(plan), "fixes": []})
        for fut in asyncio.as_completed(tasks):
            aid, plan, mode, provider, fixes, learned = await fut
            plans[aid] = plan
            self.last_plan[aid] = plan
            self.learner.log_plan(self.agents[aid], econ, plan)
            yield self._emit({"type": "decision", "day": day, "agent": aid, "mode": mode, "provider": provider,
                              "thought": plan.get("thought", ""), "plan": self._plan_public(plan), "fixes": fixes,
                              **({"learned": learned.shown} if learned.shown else {})})

        # 3. phases
        talked_today: set = set()
        bank_visited: Dict[str, bool] = {}
        self._restrictions_yesterday = econ.restrictions_today()
        for phase in PHASES:
            for ev in self._run_phase_moves(phase, plans):
                yield ev
            for ev in self._run_phase_actions(phase, plans, bank_visited):
                yield ev
            async for ev in self._run_conversations(phase, plans, talked_today):
                yield ev

        # 4. night
        for ev in self._run_night(plans, bank_visited):
            yield ev

        # 5. reflect
        async for ev in self._run_reflections():
            yield ev

        snaps = {a.id: self._snapshot(a) for a in self.agents.values()}
        for aid, plan in plans.items():
            self.learner.update_plan(aid, plan)
        rewards = self.learner.end_of_day(day, self.agents, snaps, self.title)
        yield self._emit({"type": "day_end", "day": day, "agents": snaps, "town": self._town_stats(), "rewards": rewards})

    # ── thinking ────────────────────────────────────────────────────────────
    def _needs_thinking(self, a: Agent, max_importance: int) -> bool:
        day = self.econ.day
        if a.id not in self.last_plan or max_importance >= 5:
            return True
        if day - self.last_think_day.get(a.id, 0) >= RETHINK_EVERY:
            return True
        if day > 1 and self.econ.restrictions_today() != self._restrictions_yesterday:
            return True   # a lockdown or closures began or ended: everybody replans
        if any(b["day"] <= day + 1 for b in self.econ.bills_due(a, 1)):
            return True
        if a.daily_grocery_need > 0 and a.pantry_days < 2.5:
            return True
        if a.fuel_litres_per_day > 0 and a.fuel_days < 1.5:
            return True
        if a.chronic_condition and a.medicine_days < 4:
            return True
        if a.workplace and PLACES.get(a.workplace) is not None:
            wp = PLACES[a.workplace]
            if self.econ.place_open(wp) != self.econ.place_open(wp, day - 1):
                return True   # weekday <-> weekend change
        return False

    async def _think(self, a: Agent, today_notes: List[str]):
        query = " ".join(today_notes[-4:]) or f"{a.job_title} money food bills plans"
        mems = self.memory.retrieve(a.id, query, self.econ.day, k=6)
        beliefs = self.memory.recent(a.id, 2, kinds=("reflection",))
        self.last_think_day[a.id] = self.econ.day
        mode = self.brain.kind
        learned = self.learner.context(a, self.econ, today_notes, self.agents)
        try:
            raw, provider = await self.brain.decide(a, self.econ, self.agents, today_notes, mems, beliefs, learned=learned)
        except LLMUnavailable as e:
            logger.warning("Agent %s: LLM unavailable (%s); falling back", a.id, e)
            self.stats["fallbacks"] += 1
            if a.id in self.last_plan:
                plan = self._routine_plan(a)
                plan["thought"] = "(no LLM available — kept to yesterday's routine)"
                return a.id, plan, "fallback", "", [], Learned()
            raw, provider = await MockBrain(self.econ.day).decide(a, self.econ, self.agents, today_notes, mems, beliefs,
                                                                  learned=learned)
            mode = "fallback"
        plan, fixes = normalise_decision(raw, a, self.agents)
        if mode == "llm":
            self.stats["llm_decisions"] += 1
        if plan.get("thought"):
            self.memory.add(a.id, self.econ.day, "morning", "plan", f"I decided: {plan['thought']}", 3)
        return a.id, plan, mode, provider, fixes, learned

    def _routine_plan(self, a: Agent) -> dict:
        last = self.last_plan.get(a.id)
        if last is None:
            return {"thought": "(routine)", **{ph: {"place": a.home, "do": "rest", "spend": 0} for ph in PHASES},
                    "money": {"borrow_bank": 0, "borrow_moneylender": 0, "repay_extra": 0, "send_home": 0, "skip": []},
                    "talk_to": "", "talk_about": ""}
        plan = copy.deepcopy(last)
        bills = sum(b["amount"] for b in self.econ.bills_due(a, 7))
        for ph in PHASES:
            step = plan[ph]
            cat = category_for(step["place"], step["do"])
            if cat in ("groceries", "medicine", "fuel"):
                step["spend"] = 0
            elif cat and a.money < 2 * bills:
                step["spend"] = 0
        plan["money"] = {"borrow_bank": 0, "borrow_moneylender": 0, "repay_extra": 0, "send_home": 0, "skip": []}
        plan["talk_to"] = ""
        plan["thought"] = "(routine) Nothing new today; same as yesterday."
        return plan

    @staticmethod
    def _plan_public(plan: dict) -> dict:
        return {k: plan[k] for k in ("morning", "afternoon", "evening", "money", "talk_to", "talk_about") if k in plan}

    # ── phases ──────────────────────────────────────────────────────────────
    def _run_phase_moves(self, phase: str, plans: Dict[str, dict]) -> List[dict]:
        evs = []
        for a in self.agents.values():
            step = plans[a.id][phase]
            blocked = self.econ.access_blocked(PLACES[step["place"]])
            if blocked:
                evs.extend(self._stay_home(a, phase, step))
            target = step["place"]
            if target != a.location:
                evs.append(self._emit({"type": "move", "day": self.econ.day, "phase": phase, "agent": a.id,
                                       "from": a.location, "to": target}))
                a.location = target
        return evs

    def _stay_home(self, a: Agent, phase: str, step: dict) -> List[dict]:
        """Lockdown: the planned trip is not allowed. Office staff and students work from home."""
        place = PLACES[step["place"]]
        was_work = step["do"] in ("work", "study") and step["place"] == a.workplace
        if was_work and (a.pay_type == "monthly" or a.job_key == "college_student"):
            out = Outcome(True, ("Studied online from home" if a.job_key == "college_student"
                                 else "Worked from home during the lockdown") + f" in the {phase}", 1)
        elif was_work:
            out = Outcome(False, f"Couldn't go to {place.name}: lockdown, nobody is allowed out and there is no pay today", 7)
        else:
            out = Outcome(False, f"Wasn't allowed to go to {place.name} during the lockdown; stayed at home",
                          7 if step["spend"] > 0 else 3)
        step.update(place=a.home, do="rest", spend=0.0)
        ev = self._remember_outcome(a.id, phase, out)
        return [self._emit(ev)] if ev else []

    def _run_phase_actions(self, phase: str, plans: Dict[str, dict], bank_visited: Dict[str, bool]) -> List[dict]:
        econ = self.econ
        evs = []
        # a shop with an owner is open whenever the owner is there, whatever they are doing
        for a in self.agents.values():
            if a.pay_type == "business" and a.location == a.workplace:
                econ.owner_present[(a.workplace, phase)] = True
        order = sorted(self.agents.values(), key=lambda a: 0 if a.pay_type == "business" else 1)
        for a in order:
            step = plans[a.id][phase]
            pid, do, spend = step["place"], step["do"], step["spend"]
            place = PLACES[pid]
            out: Optional[Outcome] = None
            if do in ("work", "study") and pid == a.workplace:
                if a.job_key == "college_student":
                    out = Outcome(True, f"Attended college in the {phase}", 1)
                else:
                    out = econ.do_work(a, phase)
            elif do == "work" and pid != a.workplace:
                out = Outcome(False, f"Went to {place.name} but that isn't where I work", 2)
            elif pid == "bank" or do == "bank":
                if econ.place_open(place):
                    bank_visited[a.id] = True
                    amt = plans[a.id]["money"].get("borrow_bank", 0)
                    if amt > 0:
                        out = econ.apply_loan(a, amt)
                        plans[a.id]["money"]["borrow_bank"] = 0
                else:
                    out = Outcome(False, "The bank was closed", 3)
            if out is None and (spend > 0 or do in ("shop", "eat_out", "leisure")):
                cat = category_for(pid, do) or (place.sells[0] if place.sells else None)
                if cat and spend > 0:
                    open_, why = econ.shop_open(place, phase, self.agents)
                    if not open_:
                        out = Outcome(False, why, 5)
                    else:
                        out = econ.buy(a, place, cat, spend, owner=econ.owner_of(pid, self.agents), phase=phase)
                        self._price_perception(a, place.id, cat, out)
                elif cat is None and spend > 0:
                    out = Outcome(False, f"There was nothing to buy at {place.name}", 2)
            if out is not None:
                ev = self._remember_outcome(a.id, phase, out)
                if ev:
                    evs.append(self._emit(ev))
        # salaried workers who stayed away on a workday
        if phase == "afternoon":
            for a in self.agents.values():
                wp = PLACES.get(a.workplace or "")
                if (a.pay_type == "monthly" and a.employed and wp is not None and econ.place_open(wp)
                        and all(plans[a.id][ph]["place"] != a.workplace for ph in ("morning", "afternoon"))):
                    ev = self._remember_outcome(a.id, phase, Outcome(False, "Skipped work today; my manager noticed", 5))
                    if ev:
                        evs.append(self._emit(ev))
        return evs

    def _price_perception(self, a: Agent, place_id: str, cat: str, out: Outcome) -> None:
        if not out.ok or "price_mult" not in out.data:
            return
        mult = out.data["price_mult"] / PLACES[place_id].price_index
        last = self.seen_prices[a.id].get(cat)
        self.seen_prices[a.id][cat] = (mult, self.econ.day)
        if last is None:
            last = (1.0, 0)   # they remember normal prices
        change = mult / last[0] - 1
        if abs(change) >= 0.03:
            when = "before" if last[1] == 0 else f"on day {last[1]}"
            word = "more" if change > 0 else "less"
            self._note(a.id, f"{cat.replace('_', ' ').capitalize()} cost {abs(change):.0%} {word} than {when}",
                       7 if abs(change) >= 0.1 else 6)

    async def _run_conversations(self, phase: str, plans: Dict[str, dict], talked: set) -> AsyncIterator[dict]:
        econ = self.econ
        at: Dict[str, List[Agent]] = {}
        for a in self.agents.values():
            at.setdefault(a.location, []).append(a)
        pairs: List[Tuple[Agent, Agent, str, str]] = []
        # 1) someone chose to talk to a person who is here
        for a in self.agents.values():
            tid = plans[a.id].get("talk_to")
            if not tid or a.id in talked or tid in talked:
                continue
            b = self.agents.get(tid)
            if b and b.location == a.location:
                pairs.append((a, b, a.location, plans[a.id].get("talk_about", "")))
                talked.update({a.id, b.id})
        # 2) people who know each other bump into each other at social places
        for pid, group in at.items():
            if pid not in SOCIAL_PLACES and PLACES[pid].kind != "home":
                continue
            if phase != "evening" and PLACES[pid].kind == "home":
                continue
            free = [x for x in group if x.id not in talked]
            self.rng.shuffle(free)
            for i, a in enumerate(free):
                for b in free[i + 1:]:
                    if a.id in talked or b.id in talked:
                        continue
                    if b.id in a.knows and self.rng.random() < 0.35:
                        pairs.append((a, b, pid, ""))
                        talked.update({a.id, b.id})
        pairs = pairs[: self.max_talks_per_phase]
        if not pairs:
            return

        async def talk(a, b, pid, topic):
            q = topic or "money prices work family"
            # what's on their mind, plus the latest news each has seen (people gossip about news)
            am = self.memory.retrieve(a.id, q, econ.day, k=4) + self.memory.recent(a.id, 2, kinds=("news",))
            bm = self.memory.retrieve(b.id, q, econ.day, k=4) + self.memory.recent(b.id, 2, kinds=("news",))
            try:
                raw, provider = await self.brain.converse(a, b, f"{PLACES[pid].name}, in the {phase}", topic, econ, am, bm)
            except LLMUnavailable:
                return None
            return a, b, pid, raw, provider

        for fut in asyncio.as_completed([talk(*p) for p in pairs]):
            res = await fut
            if res is None:
                continue
            a, b, pid, raw, provider = res
            learned = {a.id: str(raw.get(f"{a.id}_learned", "") or ""), b.id: str(raw.get(f"{b.id}_learned", "") or "")}
            imps = {}
            for x, other in ((a, b), (b, a)):
                try:
                    imps[x.id] = int(raw.get(f"{x.id}_importance", 4))
                except (TypeError, ValueError):
                    imps[x.id] = 4
                text = learned[x.id] or f"Chatted with {other.name}"
                self.memory.add(x.id, econ.day, phase, "conversation",
                                f"Talked with {other.name} at {PLACES[pid].name}: {text}", imps[x.id])
            self.stats["conversations"] += 1
            self.learner.log_talk(econ.day, a.id, b.id, plans[a.id].get("talk_about", "") or plans[b.id].get("talk_about", ""), learned)
            yield self._emit({"type": "conversation", "day": econ.day, "phase": phase, "place": pid,
                              "a": a.id, "b": b.id, "dialogue": raw.get("dialogue", [])[:6],
                              "learned": learned, "importance": imps, "provider": provider})

    def _run_night(self, plans: Dict[str, dict], bank_visited: Dict[str, bool]) -> List[dict]:
        econ = self.econ
        evs = []
        for a in self.agents.values():
            m = plans[a.id]["money"]
            outs: List[Outcome] = []
            if m.get("borrow_bank", 0) > 0 and not bank_visited.get(a.id):
                outs.append(Outcome(False, "Wanted a bank loan but never went to the bank", 3))
            if m.get("borrow_moneylender", 0) > 0:
                outs.append(econ.moneylender(a, m["borrow_moneylender"]))
            if m.get("send_home", 0) > 0 and a.migrant_from:
                amt = min(m["send_home"], a.money)
                if amt > 0:
                    a.money -= amt
                    a.remitted += amt
                    outs.append(Outcome(True, f"Sent ₹{amt:,.0f} home to family in {a.migrant_from}", 6, amount=amt))
            if m.get("repay_extra", 0) > 0:
                amt = min(m["repay_extra"], a.money)
                if a.khata_due > 0 and amt > 0:
                    k = min(a.khata_due, amt)
                    a.khata_due -= k
                    a.money -= k
                    amt -= k
                    outs.append(Outcome(True, f"Cleared ₹{k:,.0f} of the kirana credit", 4, amount=k))
                if amt > 0:
                    outs.append(econ.repay_extra(a, amt))
            for o in outs:
                ev = self._remember_outcome(a.id, "evening", o, kind="money")
                if ev:
                    evs.append(self._emit(ev))
        for owner, out in econ.business_close_of_day(self.agents):
            ev = self._remember_outcome(owner.id, "evening", out, kind="business")
            if ev:
                evs.append(self._emit(ev))
        for a in self.agents.values():
            went_out = any(plans[a.id][ph]["place"] != a.home for ph in PHASES)
            for o in econ.settle_bills(a, plans[a.id]["money"].get("skip", [])) + econ.end_of_day_consumption(a, went_out):
                ev = self._remember_outcome(a.id, "evening", o, kind="bill" if "pay" in o.text.lower() or "EMI" in o.text else "household")
                if ev:
                    evs.append(self._emit(ev))
        # today's experiences become memories, and are "new since yesterday" in tomorrow's prompt
        self.memory.add_many([(aid, econ.day, "evening", "observation", t, imp)
                              for aid, notes in self.pending_notes.items() for t, imp in notes if imp >= 2])
        self.carry_notes = {aid: [n for n in notes if n[1] >= 2] for aid, notes in self.pending_notes.items()}
        self.pending_notes = {aid: [] for aid in self.agents}
        return evs

    async def _run_reflections(self) -> AsyncIterator[dict]:
        econ = self.econ
        due = []
        for a in self.agents.values():
            if econ.day - self.last_reflect_day[a.id] < MIN_DAYS_BETWEEN_REFLECTIONS:
                continue
            if self.memory.importance_since(a.id, self.last_reflect_day[a.id] + 0.95) >= REFLECT_THRESHOLD:
                due.append(a)

        async def go(a):
            mems = [m for m in self.memory.all(a.id) if m.day > self.last_reflect_day[a.id]][-18:]
            try:
                insights, provider = await self.brain.reflect(a, econ, mems)
            except LLMUnavailable:
                return None
            return a, insights, provider

        for fut in asyncio.as_completed([go(a) for a in due]):
            res = await fut
            if res is None:
                continue
            a, insights, provider = res
            self.last_reflect_day[a.id] = econ.day
            self.memory.add_many([(a.id, econ.day, "night", "reflection", s, 8) for s in insights])
            self.stats["reflections"] += 1
            yield self._emit({"type": "reflection", "day": econ.day, "agent": a.id, "insights": insights,
                              "provider": provider})


def make_brain(kind: str = "auto"):
    """'llm' (needs keys), 'mock' (offline), or 'auto' (llm if any key is configured)."""
    from town.llm_pool import LLMPool
    if kind == "mock":
        return MockBrain()
    pool = LLMPool()
    if kind == "llm" and not pool.available:
        raise LLMUnavailable("ECOSIM brain 'llm' requested but no API keys are configured")
    if pool.available:
        return LLMBrain(pool)
    return MockBrain()
