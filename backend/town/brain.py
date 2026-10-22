"""
brain.py — how an agent thinks: the prompts, the decision format, and two brains.

  LLMBrain  — the real thing: the agent's situation, retrieved memories and
              beliefs go to an LLM, which writes a first-person reason and a
              plan for the day in JSON. Also runs conversations and reflection.
  MockBrain — a rule-based stand-in for tests and for running with no API key.
              It is labelled "mock" everywhere it appears and is NOT the agent
              model; it exists so the town can be exercised offline.

The economy (town/economy.py) validates and executes whatever the brain decides.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from town.economy import TownEconomy
from town.memory import Memory, MemoryStore
from town.population import Agent
from town.world import PHASES, PLACES

ACTIVITIES = ("work", "study", "shop", "eat_out", "leisure", "bank", "socialise", "rest")
CATEGORY_FOR = {  # (place, activity) -> spending category
    ("mall", "shop"): "shopping", ("mall", "leisure"): "entertainment",
}


def category_for(place_id: str, activity: str) -> Optional[str]:
    if (place_id, activity) in CATEGORY_FOR:
        return CATEGORY_FOR[(place_id, activity)]
    p = PLACES.get(place_id)
    if p is None or not p.sells:
        return None
    if activity in ("shop", "eat_out"):
        return p.sells[0]
    return None


# ── prompt building ─────────────────────────────────────────────────────────
SYSTEM_DECIDE = """You are {name}, a real person living in a small Indian town. Each morning you plan your own day.
Think like this person would: your money, bills, food at home, work, family, health, and what you have seen and heard.
You cannot spend money you do not have (except small credit at the kirana if you know the owner).
Nobody tells you what to do. Reply with ONE JSON object only, no other text."""

DECISION_FORMAT = """Reply in this JSON format:
{{
  "thought": "1-3 sentences in first person: what you are worried about or hoping for today and why you chose this plan",
  "morning":   {{"place": "<place id>", "do": "<activity>", "spend": <rupees, 0 if none>}},
  "afternoon": {{"place": "<place id>", "do": "<activity>", "spend": <rupees>}},
  "evening":   {{"place": "<place id>", "do": "<activity>", "spend": <rupees>}},
  "money": {{"borrow_bank": 0, "borrow_moneylender": 0, "repay_extra": 0, "send_home": 0, "skip": []}},
  "talk_to": "<id of someone you know, or empty>",
  "talk_about": "<what you want to talk about, or empty>"
}}
Use only the place ids listed (or your home / your workplace). Activities: {activities}. "spend" is what you plan to spend at that place (groceries, medicine, fuel, food, shopping or a movie, depending on the place).
"skip" lists payments due today you deliberately won't pay (e.g. "rent", "credit card EMI"); skipping hurts your credit score.
"borrow_bank" needs a visit to the bank that day and may be refused; "borrow_moneylender" is always available but costs 8% a week."""


PLACE_NOTES = {
    "kirana": "groceries; regulars can buy on credit (khata)",
    "supermarket": "groceries, a bit cheaper",
    "market": "groceries, cheapest; busy and chatty",
    "pharmacy": "medicine", "clinic": "doctor and medicine",
    "fuel_station": "petrol", "cafe": "tea and snacks", "restaurant": "family dinners (pricey)",
    "mall": "shopping (do: shop) or a movie (do: leisure)",
    "bank": "loans, savings", "park": "free; walk and talk",
}


def places_text(econ: TownEconomy) -> str:
    wd = econ.weekday()
    rows = []
    for p in PLACES.values():
        if p.kind == "home":
            continue
        bits = [PLACE_NOTES.get(p.id, p.name)]
        if p.sells:
            idx = econ.price_at(p, p.sells[0])
            if abs(idx - 1.0) > 0.005:
                bits.append(f"prices {idx:.2f}x normal")
        if not econ.place_open(p):
            why = econ.closed_reason(p)
            bits.append("CLOSED today" if why.startswith("closed on") else "CLOSED (" + why.replace("closed ", "") + ")")
        rows.append(f"- {p.id}: " + "; ".join(bits))
    return "\n".join(rows)


def situation_text(agent: Agent, econ: TownEconomy, agents: Dict[str, Agent]) -> str:
    lines = [agent.bio()]
    lines.append(f"Money now: ₹{agent.money:,.0f}" + (f"; you owe the kirana ₹{agent.khata_due:,.0f}" if agent.khata_due else ""))
    if agent.daily_grocery_need > 0:
        lines.append(f"Food at home: about {agent.pantry_days:.1f} days left (your household uses about "
                     f"₹{agent.daily_grocery_need * econ.price_multiplier('groceries'):,.0f} of groceries a day at today's prices)")
    if agent.fuel_litres_per_day > 0:
        lines.append(f"Fuel: about {agent.fuel_days:.1f} days left; petrol is ₹{econ.fuel_price():.0f}/litre")
    if agent.chronic_condition:
        lines.append(f"Medicine: {agent.medicine_days:.0f} days left")
    if agent.workplace and agent.pay_type in ("daily", "self", "monthly", "business"):
        if not agent.employed:
            lines.append("Work: you have lost your job.")
        else:
            wp = PLACES[agent.workplace]
            open_today = econ.place_open(wp) or (agent.pay_type == "self" and not econ.lockdown_active())
            lines.append(f"Work: {wp.id} ({wp.name}) — " + ("open today" if open_today else "closed today")
                         + {"daily": "; you're only paid for shifts you turn up for",
                            "self": "; you earn only when you go out to work",
                            "business": "; your shop only opens and earns when you are there",
                            "monthly": "; salary comes on the 1st. On workdays you are expected there in the "
                                       "morning or the afternoon (or both); missing both counts as skipping work"}[agent.pay_type])
    if agent.loans:
        lines.append("Loans: " + "; ".join(l.describe() + (" (DEFAULTED)" if l.defaulted else "") for l in agent.loans))
    lines.append(f"Credit score: {agent.credit_score}")
    bills = econ.bills_due(agent, 7)
    if bills:
        lines.append("Payments due soon: " + "; ".join(f"day {b['day']}: {b['what']} ₹{b['amount']:,.0f}" for b in bills))
    if agent.remittance_target:
        lines.append(f"Sent home so far this month: ₹{agent.remitted:,.0f} of the ₹{agent.remittance_target:,.0f} you planned")
    lines.append("Your goals: " + "; ".join(agent.goals))
    known = sorted(agent.knows.items(), key=lambda kv: {"neighbour": 0, "co-worker": 1, "friend": 2}.get(kv[1], 3))[:7]
    if known:
        lines.append("People you know: " + "; ".join(
            f"{aid} {agents[aid].name} ({rel}, {agents[aid].job_title})" for aid, rel in known if aid in agents))
    return "\n".join(lines)


def memory_text(mems: List[Memory]) -> str:
    if not mems:
        return "(nothing notable yet)"
    return "\n".join(f"- day {m.day} {m.phase}: {m.text}" for m in sorted(mems, key=lambda m: m.t))


def build_decision_prompt(agent: Agent, econ: TownEconomy, agents: Dict[str, Agent],
                          today_notes: List[str], memories: List[Memory], beliefs: List[Memory],
                          learned_text: str = "") -> Tuple[str, str]:
    system = SYSTEM_DECIDE.format(name=agent.name)
    user = "\n\n".join([
        f"Today is day {econ.day} of the month, a {econ.weekday()}.",
        "ABOUT YOU\n" + situation_text(agent, econ, agents),
        "NEW SINCE YESTERDAY\n" + ("\n".join(f"- {n}" for n in today_notes) if today_notes else "- nothing new"),
        "WHAT YOU REMEMBER\n" + memory_text(memories),
        "WHAT YOU HAVE CONCLUDED\n" + ("\n".join(f"- {b.text}" for b in beliefs) if beliefs else "- (nothing yet)"),
        *([learned_text] if learned_text else []),
        f"PLACES (your home is {agent.home})\n" + places_text(econ),
        *([ "RULES IN FORCE\n" + "\n".join(f"- {r}" for r in econ.rules_text()) ] if econ.rules_text() else []),
        DECISION_FORMAT.format(activities=", ".join(ACTIVITIES)),
    ])
    return system, user


# ── validation / normalisation of a decision ────────────────────────────────
def normalise_decision(raw: dict, agent: Agent, agents: Dict[str, Agent]) -> Tuple[dict, List[str]]:
    """Coerce an LLM decision into a safe, executable plan. Returns (plan, fixes)."""
    fixes: List[str] = []
    plan = {"thought": str(raw.get("thought", "")).strip()[:600]}
    for ph in PHASES:
        step = raw.get(ph) or {}
        if not isinstance(step, dict):
            step = {}
        pid = str(step.get("place", agent.home)).strip()
        if pid not in PLACES:
            match = next((p.id for p in PLACES.values() if pid.lower() in (p.id, p.name.lower())), None)
            if match is None:
                fixes.append(f"{ph}: unknown place '{pid}', stayed home")
                pid = agent.home
            else:
                pid = match
        do = str(step.get("do", "rest")).strip().lower().replace(" ", "_")
        if do not in ACTIVITIES:
            do = "shop" if PLACES[pid].sells else ("work" if pid == agent.workplace else "rest")
        try:
            spend = float(step.get("spend", 0) or 0)
        except (TypeError, ValueError):
            spend = 0.0
        plan[ph] = {"place": pid, "do": do, "spend": max(0.0, round(spend, 0))}
    money = raw.get("money") or {}
    if not isinstance(money, dict):
        money = {}

    def num(k):
        try:
            return max(0.0, float(money.get(k, 0) or 0))
        except (TypeError, ValueError):
            return 0.0
    skip = money.get("skip") or []
    if isinstance(skip, str):
        skip = [skip]
    plan["money"] = {"borrow_bank": num("borrow_bank"), "borrow_moneylender": num("borrow_moneylender"),
                     "repay_extra": num("repay_extra"), "send_home": num("send_home"),
                     "skip": [str(s)[:40] for s in skip][:5]}
    # "spend" where nothing is sold: at the bank it means paying down a loan; elsewhere it's dropped
    for ph in PHASES:
        step = plan[ph]
        if step["spend"] > 0 and category_for(step["place"], step["do"]) is None and not PLACES[step["place"]].sells:
            if step["place"] == "bank":
                plan["money"]["repay_extra"] += step["spend"]
                fixes.append(f"{ph}: ₹{step['spend']:.0f} at the bank treated as a loan repayment")
            step["spend"] = 0.0
    talk =str(raw.get("talk_to", "") or "").strip()
    if talk and talk not in agents:
        by_name = {a.name.lower(): a.id for a in agents.values()}
        talk = by_name.get(talk.lower(), next((aid for n, aid in by_name.items() if talk.lower() in n), ""))
    plan["talk_to"] = talk if talk != agent.id else ""
    plan["talk_about"] = str(raw.get("talk_about", "") or "")[:160]
    return plan, fixes


def validate_decision(raw: dict) -> Optional[str]:
    if not isinstance(raw, dict):
        return "not an object"
    missing = [ph for ph in PHASES if not isinstance(raw.get(ph), dict)]
    if len(missing) == 3:
        return "missing morning/afternoon/evening plans"
    if not str(raw.get("thought", "")).strip():
        return "missing 'thought'"
    return None


# ── conversation and reflection prompts ─────────────────────────────────────
SYSTEM_TALK = """You write a short, realistic conversation between two neighbours in a small Indian town.
They speak naturally (simple English, a few Hindi/Kannada words are fine). They only know what is listed for them.
Do not invent facts about their lives (children, projects, deadlines, prices, offers) beyond what is listed.
Greetings must match the time of day. Any promise they make is only a plan, not something already done.
Reply with ONE JSON object only."""

TALK_FORMAT = """Reply in this JSON format:
{{
  "dialogue": [{{"speaker": "{a}", "text": "..."}}, {{"speaker": "{b}", "text": "..."}}, ...],   (2 to 6 lines)
  "{a}_learned": "what {a_name} takes away from this, in one sentence (or empty)",
  "{b}_learned": "what {b_name} takes away from this, in one sentence (or empty)",
  "{a}_importance": <1-10, how much this matters to {a_name}>,
  "{b}_importance": <1-10, how much this matters to {b_name}>
}}"""


def build_talk_prompt(a: Agent, b: Agent, place_name: str, topic: str, econ: TownEconomy,
                      a_mems: List[Memory], b_mems: List[Memory]) -> Tuple[str, str]:
    def brief(x: Agent, mems: List[Memory]) -> str:
        news = [m for m in mems if m.kind == "news"]
        rest = [m for m in mems if m.kind != "news"]
        text = (f"{x.id} {x.name}: {x.bio()}\n  Money ₹{x.money:,.0f}, food at home {x.pantry_days:.0f} days.\n"
                f"  On their mind:\n" + "\n".join(f"  - {m.text}" for m in rest[:4]))
        bills = econ.bills_due(x, 10)
        if bills:
            text += "\n  Payments due soon: " + "; ".join(f"day {b['day']} {b['what']} ₹{b['amount']:,.0f}" for b in bills)
        if news:
            text += "\n  News they have seen:\n" + "\n".join(f"  - {m.text}" for m in news[:2])
        return text
    user = "\n\n".join([
        f"Day {econ.day} ({econ.weekday()}), at {place_name}.",
        f"{a.name} and {b.name} know each other ({a.knows.get(b.id, 'acquaintance')}).",
        brief(a, a_mems), brief(b, b_mems),
        f"{a.name} wants to talk about: {topic or 'how things are going'}",
        TALK_FORMAT.format(a=a.id, b=b.id, a_name=a.name, b_name=b.name),
    ])
    return SYSTEM_TALK, user


def validate_talk(a_id: str, b_id: str):
    def v(raw: dict) -> Optional[str]:
        d = raw.get("dialogue")
        if not isinstance(d, list) or len(d) < 2:
            return "dialogue must be a list of at least 2 lines"
        if not all(isinstance(x, dict) and x.get("speaker") in (a_id, b_id) and x.get("text") for x in d):
            return f"each line needs speaker {a_id} or {b_id} and text"
        return None
    return v


SYSTEM_REFLECT = """You help a person in a small Indian town step back and make sense of their recent days.
Write their own conclusions in first person: what is changing, what it means for them, what they will do differently.
Reply with ONE JSON object only."""


def build_reflect_prompt(agent: Agent, econ: TownEconomy, mems: List[Memory]) -> Tuple[str, str]:
    user = "\n\n".join([
        f"{agent.bio()}\nMoney now: ₹{agent.money:,.0f}. Day {econ.day} of the month.",
        "Recent experiences:\n" + memory_text(mems),
        'Reply as {"insights": ["...", "..."]} with 1 to 3 short first-person conclusions.',
    ])
    return SYSTEM_REFLECT, user


# ── brains ──────────────────────────────────────────────────────────────────
class LLMBrain:
    kind = "llm"

    def __init__(self, pool):
        self.pool = pool

    async def decide(self, agent, econ, agents, today_notes, memories, beliefs, learned=None) -> Tuple[dict, str]:
        system, user = build_decision_prompt(agent, econ, agents, today_notes, memories, beliefs,
                                             learned.text if learned else "")
        raw, provider = await self.pool.chat_json(system, user, max_tokens=420, temperature=0.7,
                                                  validate=validate_decision)
        return raw, provider

    async def converse(self, a, b, place_name, topic, econ, a_mems, b_mems) -> Tuple[dict, str]:
        system, user = build_talk_prompt(a, b, place_name, topic, econ, a_mems, b_mems)
        raw, provider = await self.pool.chat_json(system, user, max_tokens=380, temperature=0.85,
                                                  validate=validate_talk(a.id, b.id))
        return raw, provider

    async def reflect(self, agent, econ, mems) -> Tuple[List[str], str]:
        system, user = build_reflect_prompt(agent, econ, mems)
        raw, provider = await self.pool.chat_json(
            system, user, max_tokens=220, temperature=0.6,
            validate=lambda r: None if isinstance(r.get("insights"), list) and r["insights"] else "need insights list")
        return [str(s)[:240] for s in raw["insights"][:3]], provider


DISTIL_SYSTEM = (
    "You help a person in an Indian town learn from the last month. Given what happened to them each day and a few "
    "candidate lessons found by a program, write the lessons they would really take away, in the first person, "
    "specific and practical (what to do or avoid, and when). Keep each under 45 words. Output JSON only.")


def build_distil_prompt(agent, title, headlines, recs, cands) -> Tuple[str, str]:
    from town.learning import mood, plan_text
    worst = sorted(recs, key=lambda r: r.reward)[:3]
    best = [r for r in sorted(recs, key=lambda r: -r.reward)[:2] if r.reward > 0.1]
    def line(r):
        what = "; ".join(o["text"] for o in sorted(r.outcomes, key=lambda o: -o["importance"])[:2])
        return f"- day {r.day} (reward {r.reward:+.1f}, {mood(r.reward)}): I {plan_text(r.plan) or 'stayed home'}. {what}"
    user = "\n\n".join([
        f"You are {agent.name}, {agent.job_title}. The month was: {title}. News: " + " | ".join(headlines[:3]),
        "THE WORST DAYS\n" + "\n".join(line(r) for r in worst),
        "THE BEST DAYS\n" + ("\n".join(line(r) for r in best) if best else "- none"),
        "CANDIDATE LESSONS\n" + "\n".join(f"{i}. [{c['kind']}] {c['text']}" for i, c in enumerate(cands, 1)),
        'Reply as JSON: {"lessons": [{"text": "...", "kind": "do" or "avoid", "based_on": [candidate numbers, or empty]}]} '
        "with at most 4 lessons. Only lessons supported by what happened.",
    ])
    return DISTIL_SYSTEM, user


def _validate_distil(r) -> Optional[str]:
    ls = r.get("lessons") if isinstance(r, dict) else None
    if not isinstance(ls, list) or not ls:
        return "need a lessons list"
    return None


async def _distil(self, agent, title, headlines, recs, cands):
    system, user = build_distil_prompt(agent, title, headlines, recs, cands)
    raw, _ = await self.pool.chat_json(system, user, max_tokens=420, temperature=0.4, validate=_validate_distil)
    out = []
    for l in raw["lessons"][:4]:
        if not isinstance(l, dict) or not str(l.get("text", "")).strip():
            continue
        based = [int(i) for i in (l.get("based_on") or []) if str(i).isdigit()]
        out.append({"text": str(l["text"]).strip()[:300], "kind": "avoid" if str(l.get("kind")) == "avoid" else "do", "based_on": based})
    return out


LLMBrain.distil = _distil


class MockBrain:
    """Offline stand-in (tests / no API key). Rule-based; clearly not the agent model."""

    kind = "mock"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    async def decide(self, agent, econ, agents, today_notes, memories, beliefs, learned=None) -> Tuple[dict, str]:
        hints = (learned.hints if learned else None) or {}
        h = lambda k: hints.get(k, 0.0)          # how strongly a lesson applies today: 0..~0.9
        need = agent.daily_grocery_need * econ.price_multiplier("groceries")
        bills = sum(b["amount"] for b in econ.bills_due(agent, 7))
        lock_owner = agent.pay_type == "business" and econ.lockdown_active()
        workday = agent.workplace and (econ.place_open(PLACES[agent.workplace]) or (agent.pay_type == "self" and not econ.lockdown_active()))
        plan = {}
        worry = []
        work_place = agent.workplace if (agent.employed and workday and agent.pay_type != "allowance") else None
        if agent.job_key == "college_student" and workday:
            work_place = "school"
        for ph in ("morning", "afternoon"):
            plan[ph] = {"place": work_place or agent.home, "do": ("study" if agent.job_key == "college_student" else "work")
                        if work_place else "rest", "spend": 0}
        evening = {"place": agent.home, "do": "rest", "spend": 0}
        if agent.pay_type == "business" and work_place:
            evening = {"place": work_place, "do": "work", "spend": 0}   # shops stay open in the evening
        if agent.daily_grocery_need and agent.pantry_days < 3 + 4 * h("stock_food"):
            days = 7 if (agent.money > need * 12 + bills or h("stock_food") > 0.3) else 4
            shop = "market" if econ.place_open(PLACES["market"]) else "kirana"
            evening = {"place": shop, "do": "shop", "spend": round(need * days, -1)}
            worry.append("food is running low")
        elif agent.chronic_condition and agent.medicine_days < 5:
            evening = {"place": "pharmacy", "do": "shop", "spend": round(agent.medicine_monthly / 2, -1)}
            worry.append("medicine is almost finished")
        elif agent.fuel_litres_per_day and agent.fuel_days < 1.5 + 2 * h("refuel_early"):
            evening = {"place": "fuel_station", "do": "shop", "spend": round(econ.fuel_price() * agent.fuel_litres_per_day * 4, -1)}
            worry.append("the tank is nearly empty")
        elif (agent.money > (bills + need * 10) * (1.5 + 2.5 * max(h("cut_discretionary"), h("bill_buffer")))
              and self.rng.random() < 0.35):
            evening = {"place": self.rng.choice(("cafe", "mall", "restaurant")), "do": "eat_out", "spend": 250}
            if evening["place"] == "mall":
                evening["do"] = "leisure"
        elif self.rng.random() < 0.25:
            evening = {"place": "park", "do": "socialise", "spend": 0}
        if lock_owner and work_place:
            evening = {"place": work_place, "do": "work", "spend": 0}   # an essential shop stays open all day
        plan["evening"] = evening
        money = {"borrow_bank": 0, "borrow_moneylender": 0, "repay_extra": 0, "send_home": 0, "skip": []}
        if agent.money < bills * 0.5 and bills > 0 and (h("avoid_moneylender") < 0.3 or agent.pantry_days < 3):
            money["borrow_moneylender"] = round(min(8000, bills - agent.money), -2)
            worry.append("bills are due and I can't cover them")
        elif agent.money < bills * 0.5 and bills > 0:
            worry.append("bills are due; I won't go to the moneylender again")
        if agent.remittance_target and agent.remitted < agent.remittance_target and agent.money > bills + need * 7:
            money["send_home"] = round(min(agent.remittance_target - agent.remitted, agent.money - bills - need * 7), -2)
        talk = ""
        if agent.knows and self.rng.random() < 0.3:
            talk = self.rng.choice(sorted(agent.knows))
        if learned and learned.shown:
            worry.append("I remember what went wrong last time")
        plan.update(money=money, talk_to=talk, talk_about="prices" if talk else "",
                    thought="[mock] " + ("Worried that " + " and ".join(worry) + "." if worry else "A normal day."))
        return plan, "mock"

    async def converse(self, a, b, place_name, topic, econ, a_mems, b_mems) -> Tuple[dict, str]:
        def share(mems):
            mems = [m for m in mems if m.kind != "plan"]
            news = [m for m in mems if m.kind == "news"]
            if news:
                return news[-1].text
            m = max(mems, key=lambda m: m.importance, default=None)
            return m.text if m else "Things are the same as always."
        sa, sb = share(a_mems), share(b_mems)
        return {"dialogue": [{"speaker": a.id, "text": f"[mock] {sa}"}, {"speaker": b.id, "text": f"[mock] {sb}"}],
                f"{a.id}_learned": f"{b.name} said: {sb}", f"{b.id}_learned": f"{a.name} said: {sa}",
                f"{a.id}_importance": 4, f"{b.id}_importance": 4}, "mock"

    async def reflect(self, agent, econ, mems) -> Tuple[List[str], str]:
        return [f"[mock] I have ₹{agent.money:,.0f} left and need to be careful."], "mock"
