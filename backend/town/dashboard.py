"""The Dashboard page's data: one run, boiled down.

Built from the events a run already wrote (`analysis.analyse` does the heavy reading), plus the run's own numbers
(the learning summary, the model usage) and the scenario's event chain and Groq brief when there is one.
Nothing here is invented: every figure comes from a stored event.
"""

from typing import Any, Dict, List, Optional

from town.analysis import analyse, rs

PRICE_KEYS = ("groceries", "fuel")


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def day_series(events: List[dict], analysis: dict) -> List[dict]:
    """One row per finished day: how the town is doing, what things cost, and the average reward."""
    rewards: Dict[int, float] = {}
    for e in events:
        if e.get("type") == "day_end":
            vals = [r.get("total", 0.0) for r in (e.get("rewards") or {}).values() if isinstance(r, dict)]
            if vals:
                rewards[e["day"]] = _mean(vals)
    rows = []
    for d in analysis["days"]:
        t, p = d.get("town", {}), d.get("prices", {})
        rows.append({
            "day": d["day"], "weekday": d.get("weekday", ""),
            "avg_money": t.get("avg_money", 0), "low_food": t.get("low_food", 0), "hungry": t.get("hungry_today", 0),
            "defaulted": t.get("defaulted", 0), "unemployed": t.get("unemployed", 0),
            "moneylender": t.get("moneylender_borrowers", 0),
            "groceries": p.get("groceries", 1), "fuel": p.get("fuel", 1), "eating_out": p.get("eating_out"),
            "fuel_price": d.get("fuel_price", 0), "news": d.get("news", []),
            "avg_reward": round(rewards[d["day"]], 3) if d["day"] in rewards else None,
        })
    return rows


def findings(a: dict) -> List[str]:
    """Plain sentences for the top of the page, each computed from the numbers."""
    k, n = a["kpis"], max(1, len(a["agents"]))
    out = []
    c = a["status_counts"]
    out.append(f"{c.get('In crisis', 0)} of {n} residents ended in crisis and {c.get('Under strain', 0)} under strain; "
               f"{c.get('Coping', 0)} coped.")
    g, f = k["grocery_price_change"], k["fuel_price_change"]
    if abs(g) >= 0.02 or abs(f) >= 0.02:
        out.append(f"Groceries moved {g * 100:+.0f}% and fuel {f * 100:+.0f}% from day 1 to the end.")
    if k["moneylender_end"] or k["defaulted_end"] or k["unemployed_end"]:
        out.append(f"{k['moneylender_end']} owed the moneylender, {k['defaulted_end']} defaulted and "
                   f"{k['unemployed_end']} were without work at the end.")
    if k["ever_hungry"]:
        out.append(f"{k['ever_hungry']} went at least one day with no food at home; at worst {k['peak_low_food']} were low on food at once.")
    out.append(f"The average resident held {rs(k['avg_money_end'])} at the end, against {rs(k['avg_money_start'])} at the start.")
    return out


def compact_agent(a: dict, mean_reward: Optional[float]) -> dict:
    return {
        "id": a["id"], "name": a["name"], "age": a.get("age"), "job": a.get("job"), "status": a["status"],
        "start_money": a["start"]["money"], "end_money": a["end"]["money"], "debt": a["end"]["debt"],
        "days_hungry": a["end"]["days_hungry"], "employed": a["end"]["employed"], "defaulted": a["end"]["defaulted"],
        "used_moneylender": a["used_moneylender"], "money_series": a["money_series"],
        "mean_reward": mean_reward,
    }


def propagation_view(rec: Optional[dict]) -> Optional[dict]:
    """The scenario's chain and brief, trimmed to what the page shows."""
    if not rec:
        return None
    keep = ("key", "kind", "title", "description", "explain", "watch", "nodes", "brief", "headlines", "shock", "shock_text",
            "rules", "tags", "status", "scenario_id", "preset_id")
    return {k: rec.get(k) for k in keep if k in rec}


def build(events: List[dict], meta: dict, record: Optional[dict] = None) -> dict:
    a = analyse(events, meta)            # raises ValueError if the run has not started
    learn = meta.get("learning_summary") or {}
    means = (learn.get("agent_means") or {}) if isinstance(learn, dict) else {}
    series = day_series(events, a)
    return {
        "run": {
            "run_id": meta.get("run_id") or a.get("run_id"), "title": a["title"], "status": a["status"],
            "created_at": meta.get("created_at"), "finished_at": meta.get("finished_at"),
            "days_planned": a["days_planned"], "days_run": a["days_run"], "seed": a.get("seed"),
            "shock": a["shock"], "shock_text": a["shock_text"], "onset_day": a["onset_day"], "full_day": a["full_day"],
            "rules": meta.get("rules") or [], "source": meta.get("source") or {},
            "brain": a["brain"], "providers": a["providers"], "memory": a["memory"], "learning_mode": meta.get("learning"),
        },
        "findings": findings(a) if a["agents"] else [],
        "kpis": a["kpis"], "status_counts": a["status_counts"],
        "series": series,
        "agents": [compact_agent(x, means.get(x["id"])) for x in a["agents"]],
        "key_events": a["key_events"][:40],
        "activity": {"conversations": a["conversations"], "reflections": a["reflections"], "decision_modes": a["decision_modes"],
                     "usage": a["usage"]},
        "learning": {"mode": meta.get("learning"), "mean_reward": learn.get("mean_reward") if isinstance(learn, dict) else None,
                     "lessons": learn.get("lessons") if isinstance(learn, dict) else None},
        "propagation": propagation_view(record),
    }
