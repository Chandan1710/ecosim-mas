"""
validation.py — "does the town behave roughly like the real thing?"

How it works
------------
1. A real event (validation_events.py, or one the user types in) gives two things: INPUTS (what was imposed from outside:
   a lockdown, a price rise, ...) and OUTCOMES (what happened to people, as published, with a source).
2. A normal town run is started with ONLY the inputs. The town is never shown the outcomes.
3. When the run ends, the same outcomes are measured from the run's event log (measure(), below). The town drifts a
   little even with no shock at all (people stock up on day 1, pay arrives on set days), so the same days are also run
   with no shock and the difference is what counts as the event's effect. Then the effect is set beside the real figures. Each is judged against a tolerance band, because 20 simulated residents can only ever be "around" the
   truth: the band is the larger of 7.5 points and a quarter of the real figure (about one or two residents).

   close    inside the band
   roughly  up to twice the band away, and moving the same way as reality
   off      further than that, or moving the opposite way

   The event's match score is the share of its figures that are close (1 point) or roughly right (half a point).

What this does not do: fit the town to the data. No setting is tuned against these figures, so a poor score is
information about the model rather than something to be hidden.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from simulation.shock import INCOME_PASS_THROUGH, Shock
from town.analysis import analyse
from town.scenarios import Rules
from town.validation_events import BY_ID, EVENTS

MIN_BAND = 7.5       # points
REL_BAND = 0.25      # of the real figure

# measure id -> what it is, in words the page shows; unit: "pp" = percentage points, "%" = percent
MEASURES: Dict[str, dict] = {
    "jobless_rise": {
        "label": "Workers without work, rise",
        "unit": "pp",
        "how": "Share of working residents who lost their job or stopped earning at all in the last 3 days, minus the same share before the shock.",
    },
    "food_short": {
        "label": "Went short of food",
        "unit": "%",
        "how": "Share of residents who ran low on food (under 2 days of groceries at home) or went hungry at any point after the shock began.",
    },
    "borrowed": {
        "label": "Borrowed informally",
        "unit": "%",
        "how": "Share of residents who borrowed from the moneylender or ran up a tab at the grocery shop after the shock began.",
    },
    "income_change": {
        "label": "Earnings of casual and self-employed workers, change",
        "unit": "%",
        "how": "Daily earnings of daily-wage and self-employed residents over the last 3 days, against the days before the shock.",
    },
    "spending_change": {
        "label": "Household spending, change",
        "unit": "%",
        "how": "Money spent in shops per day over the last 3 days, against the days before the shock (rupees, not adjusted for price changes).",
    },
}
GROUPS = {
    "all": "all residents",
    "low_income": "lower-income residents",
    "workers_daily": "daily-wage and self-employed residents",
}
_NO_WORK_PAY = ("pension", "allowance")
_EARNS_DAILY = ("daily", "self", "business")


# ── measuring a run ─────────────────────────────────────────────────────────────
def _members(agents: Dict[str, dict], group: str) -> List[str]:
    if group == "low_income":
        return [i for i, a in agents.items() if a.get("income_tier") == "low"]
    if group == "workers_daily":
        return [i for i, a in agents.items() if a.get("pay_type") in ("daily", "self")]
    return list(agents)


def measure(events: List[dict], meta: dict, measure_id: str, group: str) -> Optional[float]:
    """One outcome, measured from a run's event log. None when the run is too short to say."""
    start = next((e for e in events if e.get("type") == "run_start"), None)
    if not start:
        return None
    agents = {a["id"]: a for a in start.get("agents", [])}
    snaps = {e["day"]: e.get("agents", {}) for e in events if e.get("type") == "day_end"}
    days = sorted(snaps)
    onset = int(start.get("shock_onset_day") or 2)
    if len(days) < onset + 1:
        return None
    pre = [d for d in days if d < onset] or days[:1]
    post = days[-3:] if len(days) - len(pre) >= 3 else days[len(pre):]
    if not post:
        return None
    last, pre_last = days[-1], pre[-1]
    before_post = days[days.index(post[0]) - 1] if days.index(post[0]) > 0 else None

    def cum(aid: str, d: Optional[int], kind: str) -> float:
        if d is None:
            return 0.0
        s = snaps.get(d, {}).get(aid) or {}
        return float(s.get("earned", 0)) if kind == "earned" else float(sum((s.get("spent") or {}).values()))

    def rates(aid: str, kind: str):
        pre_rate = cum(aid, pre_last, kind) / max(1, pre_last)
        post_rate = (cum(aid, last, kind) - cum(aid, before_post, kind)) / max(1, len(post))
        return pre_rate, post_rate

    ids = _members(agents, group)
    if not ids:
        return None

    if measure_id == "jobless_rise":
        workers = [i for i in ids if agents[i].get("pay_type") not in _NO_WORK_PAY]
        if not workers:
            return None

        def share(d_after: int) -> float:
            n = 0
            for i in workers:
                s = snaps[d_after].get(i) or {}
                stopped = not s.get("employed", True)
                if not stopped and d_after == last and agents[i].get("pay_type") in _EARNS_DAILY:
                    pr, po = rates(i, "earned")
                    stopped = pr > 0 and po <= 0
                n += 1 if stopped else 0
            return n / len(workers)
        return round((share(last) - share(pre_last)) * 100, 1)

    if measure_id == "food_short":
        n = 0
        for i in ids:
            for d in days:
                if d < onset:
                    continue
                s = snaps[d].get(i) or {}
                if s.get("days_hungry", 0) > 0 or s.get("pantry_days", 9) < 2:
                    n += 1
                    break
        return round(n / len(ids) * 100, 1)

    if measure_id == "borrowed":
        used = {a["id"] for a in analyse(events, meta).get("agents", []) if a.get("used_moneylender")}
        n = 0
        for i in ids:
            tab = any((snaps[d].get(i) or {}).get("khata_due", 0) > 0 for d in days if d >= onset)
            n += 1 if (i in used or tab) else 0
        return round(n / len(ids) * 100, 1)

    if measure_id in ("income_change", "spending_change"):
        kind = "earned" if measure_id == "income_change" else "spent"
        pre_t = post_t = 0.0
        for i in ids:
            a, b = rates(i, kind)
            pre_t += a
            post_t += b
        if pre_t <= 0:
            return None
        return round((post_t / pre_t - 1) * 100, 1)
    return None


# ── the no-shock control ────────────────────────────────────────────────────────
_CONTROL: Dict[tuple, List[dict]] = {}


def control_events(days: int, pace: str, seed: int, n_agents: int) -> List[dict]:
    """The same town for the same days with no shock, on the offline brain (cheap, and the same every time).
    Runs in memory only: nothing is saved, so it never shows up in your list of runs."""
    import asyncio
    from town.engine import TownSimulation
    key = (days, pace, seed, n_agents)
    if key not in _CONTROL:
        sim = TownSimulation(shock=Shock(), n_agents=n_agents, seed=seed, days=days, title="No-shock control", pace=pace,
                             rules=Rules(), learning="off")

        async def go():
            async for _ in sim.run():
                pass
        import threading
        t = threading.Thread(target=lambda: asyncio.run(go()), daemon=True)   # its own event loop, whatever called us
        t.start()
        t.join()
        _CONTROL[key] = list(sim.events)
    return _CONTROL[key]


def net_effect(measure_id: str, event_value: Optional[float], control_value: Optional[float]) -> Optional[float]:
    """What the event added on top of the no-shock town."""
    if event_value is None or control_value is None:
        return None
    if MEASURES[measure_id]["unit"] == "%" and measure_id.endswith("_change"):
        return round(((1 + event_value / 100) / max(0.01, 1 + control_value / 100) - 1) * 100, 1)
    return round(event_value - control_value, 1)


# ── judging ─────────────────────────────────────────────────────────────────────
def band_for(real: float) -> float:
    return round(max(MIN_BAND, REL_BAND * abs(real)), 1)


def judge(real: float, sim: Optional[float]) -> dict:
    band = band_for(real)
    if sim is None:
        return {"verdict": "unknown", "gap": None, "band": band, "points": None}
    gap = round(sim - real, 1)
    same_way = (sim == 0 and real == 0) or (sim * real > 0) or abs(real) < band   # small real change: direction is not meaningful
    if abs(gap) <= band:
        verdict, pts = "close", 1.0
    elif abs(gap) <= 2 * band and same_way:
        verdict, pts = "roughly", 0.5
    else:
        verdict, pts = "off", 0.0
    return {"verdict": verdict, "gap": gap, "band": band, "points": pts}


def scorecard(event: dict, events: List[dict], meta: dict, control: Optional[List[dict]] = None) -> dict:
    rows = []
    for o in event["outcomes"]:
        m = MEASURES[o["measure"]]
        g = o.get("group", "all")
        raw = measure(events, meta, o["measure"], g)
        ctl = measure(control, {}, o["measure"], g) if control else None
        sim = net_effect(o["measure"], raw, ctl) if control else raw
        j = judge(float(o["real"]), sim)
        rows.append({
            "measure": o["measure"], "label": o.get("label") or m["label"], "unit": m["unit"], "how": m["how"],
            "group": GROUPS.get(o.get("group", "all"), "all residents"),
            "real": o["real"], "sim": sim, "raw": raw, "control": ctl, "source": o.get("source", ""), "url": o.get("url", ""), **j,
        })
    scored = [r for r in rows if r["points"] is not None]
    score = round(sum(r["points"] for r in scored) / len(scored) * 100) if scored else None
    verdict = None if score is None else ("close" if score >= 75 else "roughly" if score >= 50 else "off")
    return {
        "event": {k: event.get(k) for k in ("id", "title", "year", "summary", "inputs", "caveats", "custom")},
        "rows": rows, "score": score, "verdict": verdict,
        "counts": {v: sum(1 for r in rows if r["verdict"] == v) for v in ("close", "roughly", "off", "unknown")},
        "band_rule": f"Band: the larger of {MIN_BAND:g} points and {int(REL_BAND * 100)}% of the real figure.",
    }


# ── starting a validation run ───────────────────────────────────────────────────
def inputs_to_shock(inputs: dict) -> tuple[Shock, Rules]:
    demand = float(inputs.get("demand", 0.0))
    shock = Shock(essential_cost=float(inputs.get("essential_cost", 0.0)), income=INCOME_PASS_THROUGH * demand,
                  credit_tightness=float(inputs.get("credit_tightness", 0.0)), demand=demand, savings=0.0)
    return shock, Rules(lockdown=bool(inputs.get("lockdown")))


def event_from_custom(body: dict) -> dict:
    """An event typed in by the user: its inputs, and the real figures they want the town compared with."""
    outcomes = []
    for o in body.get("outcomes", []):
        if o.get("measure") not in MEASURES or o.get("real") in (None, ""):
            continue
        outcomes.append({"measure": o["measure"], "group": o.get("group") if o.get("group") in GROUPS else "all",
                         "real": float(o["real"]), "label": MEASURES[o["measure"]]["label"],
                         "source": (o.get("source") or "Entered by you").strip()[:200], "url": ""})
    if not outcomes:
        raise ValueError("Enter at least one real figure to compare with")
    ins = body.get("inputs", {})
    return {
        "id": "custom", "custom": True, "title": (body.get("title") or "Your event").strip()[:120], "year": None,
        "summary": (body.get("summary") or "").strip()[:500],
        "inputs": {"lockdown": bool(ins.get("lockdown")),
                   "essential_cost": max(-0.6, min(0.6, float(ins.get("essential_cost", 0) or 0))),
                   "demand": max(-0.6, min(0.6, float(ins.get("demand", 0) or 0))),
                   "credit_tightness": max(-0.6, min(0.6, float(ins.get("credit_tightness", 0) or 0))),
                   "note": "The inputs you entered."},
        "run": {"days": int(body.get("days") or 10), "pace": "fast"},
        "outcomes": outcomes, "caveats": "",
    }


def catalogue() -> List[dict]:
    out = []
    for e in EVENTS:
        out.append({**{k: e[k] for k in ("id", "title", "year", "summary", "inputs", "caveats")}, "run": e["run"],
                    "outcomes": [{k: o.get(k) for k in ("measure", "label", "group", "real", "source", "url")} for o in e["outcomes"]]})
    return out


def lookup(event_id: str) -> dict:
    if event_id not in BY_ID:
        raise LookupError(f"No event '{event_id}'")
    return BY_ID[event_id]
