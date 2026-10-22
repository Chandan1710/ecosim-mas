"""
analysis.py — turn a run's event log into findings: town indicators per day,
each agent's major decisions and pivotal points, and outcomes.

Everything here is computed from the saved events, so a report can be made for
any finished run without calling an LLM again. `write_stories` is the one
exception: after a run ends it asks the LLM to narrate each agent's month from
these findings (facts in, prose out) and saves the result next to the log.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MONEY_ACTIONS = {"borrow_bank": "asked the bank for a loan of", "borrow_moneylender": "borrowed from the moneylender",
                 "repay_extra": "paid extra towards debts", "send_home": "sent money home"}
DISCRETIONARY = ("eating_out", "shopping", "entertainment")
PIVOT_WORDS = ("defaulted", "default", "lost my job", "no job", "couldn't afford", "could not afford", "hungry",
               "refused", "approved", "moneylender", "missed", "out of food", "ran out", "no shift", "late fee",
               "fewer customers", "skipped", "empty")


def rs(x: float) -> str:
    """Rupees for PDFs and plain text (the built-in PDF fonts have no ₹ glyph)."""
    return f"Rs {x:,.0f}"


def plain(text: str) -> str:
    return (text or "").replace("₹", "Rs ").replace("  ", " ").replace("‑", "-").replace(" ", " ")


def _median(xs: List[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _status(snap: dict, hungry_days: int, used_moneylender: bool, skipped: bool, money_drop: float,
            lost_job: bool) -> str:
    if snap.get("defaulted") or lost_job or hungry_days >= 2:
        return "In crisis"
    if used_moneylender or skipped or snap.get("khata_due", 0) > 0 or hungry_days >= 1 or money_drop > 0.4:
        return "Under strain"
    return "Coping"


def analyse(events: List[dict], meta: Optional[dict] = None) -> dict:
    meta = meta or {}
    start = next((e for e in events if e.get("type") == "run_start"), None)
    if start is None:
        raise ValueError("this run has no events yet")
    end = next((e for e in events if e.get("type") == "run_end"), None)
    profiles = {a["id"]: a for a in start.get("agents", [])}
    names = {aid: p["name"] for aid, p in profiles.items()}
    onset = start.get("shock_onset_day", 3)
    full = start.get("shock_full_day", onset + 7)

    days: List[dict] = []
    cur: dict = {}
    snaps: Dict[int, Dict[str, dict]] = {}
    per: Dict[str, dict] = {aid: {"decisions": [], "pivots": [], "talks": [], "reflections": [], "money_actions": []}
                            for aid in profiles}
    modes: Dict[str, int] = {}
    last_decision: Dict[str, dict] = {}

    for e in events:
        t = e.get("type")
        if t == "day_start":
            cur = {"day": e["day"], "weekday": e.get("weekday", ""), "prices": e.get("prices", {}),
                   "fuel_price": e.get("fuel_price", 0), "news": e.get("news", [])}
        elif t == "decision":
            modes[e["mode"]] = modes.get(e["mode"], 0) + 1
            if e["mode"] in ("llm", "fallback", "mock") and e["agent"] in per:
                money = (e.get("plan") or {}).get("money") or {}
                acts = [f"{MONEY_ACTIONS[k]} {rs(money[k])}" for k in MONEY_ACTIONS if (money.get(k) or 0) > 0]
                if money.get("skip"):
                    acts.append("chose not to pay: " + ", ".join(money["skip"]))
                d = {"day": e["day"], "thought": plain(e.get("thought", "")), "plan": e.get("plan", {}),
                     "money_moves": acts, "mode": e["mode"]}
                per[e["agent"]]["decisions"].append(d)
                last_decision[e["agent"]] = d
        elif t == "action" and e.get("agent") in per:
            text = plain(e.get("text", ""))
            low = text.lower()
            pivotal = (e.get("importance", 0) >= 7 or (not e.get("ok", True) and e.get("importance", 0) >= 5)
                       or any(w in low for w in PIVOT_WORDS)
                       or e.get("kind") == "money"                                   # their own money moves
                       or (low.startswith("paid ") and (e.get("amount") or 0) >= 2500))   # big bills: rent, EMIs
            if pivotal:
                per[e["agent"]]["pivots"].append({"day": e["day"], "text": text, "importance": e.get("importance", 0)})
            if e.get("kind") == "money" and e.get("ok"):
                per[e["agent"]]["money_actions"].append({"day": e["day"], "text": text})
        elif t == "conversation":
            for x, other in ((e["a"], e["b"]), (e["b"], e["a"])):
                if x in per:
                    per[x]["talks"].append({"day": e["day"], "with": names.get(other, other), "place": e.get("place", ""),
                                            "learned": plain((e.get("learned") or {}).get(x, "")),
                                            "importance": (e.get("importance") or {}).get(x, 4),
                                            "dialogue": e.get("dialogue", [])})
        elif t == "reflection" and e.get("agent") in per:
            per[e["agent"]]["reflections"].append({"day": e["day"], "insights": [plain(s) for s in e.get("insights", [])]})
        elif t == "day_end":
            snaps[e["day"]] = e.get("agents", {})
            days.append({**cur, "day": e["day"], "town": e.get("town", {})})

    day_nums = sorted(snaps)
    last_day = day_nums[-1] if day_nums else 0

    # changes visible only in the daily snapshots: job losses, defaults, going hungry
    for aid in profiles:
        prev = {"employed": profiles[aid].get("employed", True), "defaulted": False, "days_hungry": 0}
        for d in day_nums:
            s = snaps[d].get(aid)
            if not s:
                continue
            if prev.get("employed", True) and not s.get("employed", True):
                per[aid]["pivots"].append({"day": d, "text": "Lost their job in the round of job cuts", "importance": 10})
            if not prev.get("defaulted") and s.get("defaulted"):
                per[aid]["pivots"].append({"day": d, "text": "Defaulted on a loan (two missed payments)", "importance": 10})
            if s.get("days_hungry", 0) > prev.get("days_hungry", 0) and prev.get("days_hungry", 0) == 0:
                per[aid]["pivots"].append({"day": d, "text": "First day with no food at home", "importance": 9})
            prev = s

    agents_out = []
    for aid, p in profiles.items():
        a = per[aid]
        # baseline cash = end of day 1 (salaries and pensions arrive on the 1st)
        day1 = snaps.get(day_nums[0], {}).get(aid, {}) if day_nums else {}
        first = {"money": day1.get("money", p.get("money", 0)), "credit_score": p.get("credit_score", 0),
                 "debt": sum(l.get("outstanding", 0) for l in p.get("loans", []) if isinstance(l, dict))}
        last = snaps.get(last_day, {}).get(aid, {})
        series = [snaps[d][aid]["money"] for d in day_nums if aid in snaps[d]]
        hungry = last.get("days_hungry", 0)
        used_ml = any("moneylender" in m["text"].lower() for m in a["money_actions"]) or \
            any("moneylender" in x["text"].lower() and "borrowed" in x["text"].lower() for x in a["pivots"])
        skipped = any(any("not to pay" in m for m in d["money_moves"]) for d in a["decisions"])
        start_money = first["money"] or 1
        drop = max(0.0, (start_money - last.get("money", start_money)) / max(1.0, abs(start_money)))
        lost_job = any(x["text"].startswith("Lost their job") for x in a["pivots"])
        status = _status(last, hungry, used_ml, skipped, drop, lost_job)

        # collapse repeats ("Almost out of groceries" every evening) into one line with a count
        piv: Dict[str, dict] = {}
        for x in sorted(a["pivots"], key=lambda x: x["day"]):
            key = x["text"].split("—")[0].strip()
            if key in piv:
                piv[key]["times"] += 1
                piv[key]["last_day"] = x["day"]
            else:
                piv[key] = {**x, "times": 1, "last_day": x["day"]}
        pivots = sorted(piv.values(), key=lambda x: (x["day"], -x["importance"]))

        # major decisions: the first plan, every plan that moved money, and each plan made the
        # morning after a pivotal point (how they responded)
        pivot_days = {x["day"] for x in a["pivots"]}
        major = []
        for i, d in enumerate(a["decisions"]):
            why = []
            if i == 0:
                why.append("first plan")
            if d["money_moves"]:
                why.append("money decision")
            if (d["day"] - 1) in pivot_days:
                why.append("response to the day before")
            if why:
                major.append({**d, "why": why})

        spent = last.get("spent", {})
        agents_out.append({
            "id": aid, "name": p["name"], "age": p.get("age"), "job": p.get("job_title", ""),
            "home": p.get("home", ""), "household": p.get("household_size", 1), "children": p.get("children", 0),
            "pay_type": p.get("pay_type"), "goals": p.get("goals", []), "migrant_from": p.get("migrant_from"),
            "status": status,
            "start": first, "end": {"money": last.get("money", first["money"]), "debt": last.get("debt", first["debt"]),
                                    "credit_score": last.get("credit_score", first["credit_score"]),
                                    "employed": last.get("employed", True), "defaulted": last.get("defaulted", False),
                                    "khata_due": last.get("khata_due", 0), "days_hungry": hungry,
                                    "earned": last.get("earned", 0)},
            "money_series": series, "spent": spent,
            "discretionary_spent": sum(spent.get(k, 0) for k in DISCRETIONARY),
            "llm_decisions": sum(1 for d in a["decisions"] if d["mode"] == "llm"),
            "major_decisions": major, "pivots": pivots,
            "talks": sorted(a["talks"], key=lambda x: -x["importance"]),
            "reflections": a["reflections"], "money_actions": a["money_actions"],
            "used_moneylender": used_ml,
        })

    order = {"In crisis": 0, "Under strain": 1, "Coping": 2}
    agents_out.sort(key=lambda x: (order[x["status"]], x["end"]["money"] - x["start"]["money"]))

    t0 = days[0]["town"] if days else {}
    t1 = days[-1]["town"] if days else {}
    p0 = days[0]["prices"] if days else {}
    p1 = days[-1]["prices"] if days else {}
    key_events = []
    for d in days:
        for h in d.get("news", []):
            key_events.append({"day": d["day"], "text": f"News: {plain(h)}"})
    for a in agents_out:
        for x in a["pivots"]:
            if x["importance"] >= 10:
                key_events.append({"day": x["day"], "text": f"{a['name']}: {x['text']}"})
    key_events.sort(key=lambda x: x["day"])

    counts = {s: sum(1 for a in agents_out if a["status"] == s) for s in order}
    return {
        "run_id": start.get("run_id"), "title": plain(start.get("title") or meta.get("title", "")),
        "shock": start.get("shock", {}), "shock_text": meta.get("shock_text", ""),
        "days_planned": start.get("days"), "days_run": last_day, "pace": start.get("pace", "normal"),
        "onset_day": onset, "full_day": full, "brain": start.get("brain"), "providers": start.get("providers", ""),
        "memory": start.get("memory_backend", ""), "seed": meta.get("seed"), "created_at": meta.get("created_at"),
        "status": meta.get("status", "done" if end else "incomplete"),
        "days": days, "agents": agents_out, "status_counts": counts, "key_events": key_events,
        "decision_modes": modes,
        "conversations": sum(1 for e in events if e.get("type") == "conversation"),
        "reflections": sum(1 for e in events if e.get("type") == "reflection"),
        "usage": (end or {}).get("usage", []),
        "kpis": {
            "avg_money_start": sum(a["start"]["money"] for a in agents_out) / max(1, len(agents_out)),
            "avg_money_end": t1.get("avg_money", 0),
            "median_money_start": _median([a["start"]["money"] for a in agents_out]),
            "median_money_end": _median([a["end"]["money"] for a in agents_out]),
            "cash_fell": sum(1 for a in agents_out if a["end"]["money"] < a["start"]["money"] * 0.95),
            "grocery_price_change": p1.get("groceries", 1) - p0.get("groceries", 1) if p0 else 0,
            "fuel_price_change": p1.get("fuel", 1) - p0.get("fuel", 1) if p0 else 0,
            "grocery_index_end": p1.get("groceries", 1), "fuel_index_end": p1.get("fuel", 1),
            "moneylender_end": t1.get("moneylender_borrowers", 0), "moneylender_start": t0.get("moneylender_borrowers", 0),
            "defaulted_end": t1.get("defaulted", 0), "unemployed_end": t1.get("unemployed", 0),
            "ever_hungry": sum(1 for a in agents_out if a["end"]["days_hungry"] > 0),
            "peak_low_food": max((d["town"].get("low_food", 0) for d in days), default=0),
            "shop_sales_start": t0.get("shop_sales", {}), "shop_sales_end": t1.get("shop_sales", {}),
        },
    }


# ── LLM-written stories (after a run) ────────────────────────────────────────
SYSTEM_STORY = """You write short, factual case notes about people in an economic simulation of a small Indian town.
Use ONLY the facts given. Do not invent events, numbers, family members or feelings that are not in the notes.
Write plainly, in the past tense, third person. Use "Rs" for rupees. Reply with ONE JSON object only."""


def _agent_brief(a: dict, r: dict) -> str:
    lines = [f"{a['name']}, {a['age']}, {a['job']}. Household of {a['household']}. Goals: {'; '.join(a['goals'])}.",
             f"Money: {rs(a['start']['money'])} on day 1 -> {rs(a['end']['money'])} on day {r['days_run']}. "
             f"Debt: {rs(a['start']['debt'])} -> {rs(a['end']['debt'])}. Credit score {a['start']['credit_score']} -> "
             f"{a['end']['credit_score']}. Outcome: {a['status']}.",
             f"The shock ({r['title']}) started on day {r['onset_day']} and was at full strength by day {r['full_day']}."]
    if a["pivots"]:
        lines.append("Pivotal points:\n" + "\n".join(
            f"- day {x['day']}: {x['text']}" + (f" (happened {x['times']} times)" if x["times"] > 1 else "")
            for x in a["pivots"][:10]))
    if a["major_decisions"]:
        lines.append("Their own reasoning on key days:\n" + "\n".join(
            f"- day {d['day']}: \"{d['thought'][:220]}\"" + (f" [{'; '.join(d['money_moves'])}]" if d["money_moves"] else "")
            for d in a["major_decisions"][:8]))
    if a["reflections"]:
        lines.append("Conclusions they reached:\n" + "\n".join(
            f"- day {x['day']}: " + " / ".join(x["insights"]) for x in a["reflections"]))
    talks = [t for t in a["talks"] if t["learned"]][:3]
    if talks:
        lines.append("From conversations:\n" + "\n".join(f"- day {t['day']} with {t['with']}: {t['learned']}" for t in talks))
    return "\n\n".join(lines)


async def write_stories(run_id: str, events: List[dict], meta: dict, pool) -> dict:
    """One short story per agent plus a town overview. Best effort; saved to <run_id>.stories.json."""
    from town.runs import _path
    r = analyse(events, meta)

    async def agent_story(a):
        user = _agent_brief(a, r) + '\n\nReply as {"story": "3 to 5 sentences on how this person\'s month went and why", ' \
                                    '"turning_point": "one sentence naming the single most important moment"}'
        try:
            raw, _ = await pool.chat_json(SYSTEM_STORY, user, max_tokens=320, temperature=0.4,
                                          validate=lambda x: None if str(x.get("story", "")).strip() else "missing story")
            return a["id"], {"story": plain(str(raw.get("story", ""))), "turning_point": plain(str(raw.get("turning_point", "")))}
        except Exception as e:
            logger.warning("story for %s failed: %s", a["id"], e)
            return a["id"], None

    async def town_story():
        k = r["kpis"]
        facts = [f"Scenario: {r['title']}. {r['days_run']} days, {len(r['agents'])} people.",
                 f"Shock started day {r['onset_day']}, full strength by day {r['full_day']}.",
                 f"Average cash per person: {rs(k['avg_money_start'])} -> {rs(k['avg_money_end'])}.",
                 f"Grocery prices x{k['grocery_index_end']:.2f}, fuel prices x{k['fuel_index_end']:.2f} of normal by the end.",
                 f"Borrowing from the moneylender: {k['moneylender_start']} -> {k['moneylender_end']} people. "
                 f"Defaults: {k['defaulted_end']}. Without work: {k['unemployed_end']}. Anyone who went without food: {k['ever_hungry']}.",
                 f"Outcomes: {r['status_counts']}."]
        facts += [f"day {x['day']}: {x['text']}" for x in r["key_events"][:12]]
        facts += [f"{a['name']} ({a['job']}): {a['status']}; " + "; ".join(x["text"] for x in a["pivots"][:3])
                  for a in r["agents"][:8]]
        user = "\n".join(facts) + '\n\nReply as {"summary": "5 to 7 sentences: what happened to the town and why", ' \
                                  '"lessons": ["2 to 4 short findings a policymaker could act on"]}'
        try:
            raw, _ = await pool.chat_json(SYSTEM_STORY, user, max_tokens=500, temperature=0.4,
                                          validate=lambda x: None if str(x.get("summary", "")).strip() else "missing summary")
            return {"summary": plain(str(raw.get("summary", ""))),
                    "lessons": [plain(str(s)) for s in (raw.get("lessons") or [])][:4]}
        except Exception as e:
            logger.warning("town story failed: %s", e)
            return None

    results = await asyncio.gather(town_story(), *[agent_story(a) for a in r["agents"]])
    stories = {"town": results[0], "agents": {aid: s for aid, s in results[1:] if s}}
    with open(_path(run_id, "stories.json"), "w") as f:
        json.dump(stories, f, indent=1)
    return stories
