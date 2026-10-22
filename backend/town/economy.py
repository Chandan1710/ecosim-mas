"""
economy.py — the town's economic rules. This is the "physics" the agents live in.

Agents decide; this module enforces consequences:
  * prices at each shop (the scenario shock raises them gradually)
  * whether there is work today, and what it pays
  * shop owners' profit, which depends on what other agents spend there
  * the bank: loan approval gets stricter when credit tightens
  * bills, EMIs, missed payments, credit scores and defaults
  * groceries, fuel and medicine running out

All randomness comes from one seeded RNG, so a run can be reproduced.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulation.shock import Shock
from town.population import Agent, Loan
from town.scenarios import Rules
from town.world import PLACES, Place, weekday_of

# ── constants (₹) ───────────────────────────────────────────────────────────
FUEL_PRICE_PER_LITRE = 103.0
SHOCK_ONSET_DAY = 3          # day 1-2 are normal so agents see "before"
SHOCK_RAMP_DAYS = 8          # full effect by onset + ramp
PANTRY_MAX_DAYS = 30
MEDICINE_MAX_DAYS = 60
TANK_LITRES = {"scooter": 5.0, "car": 40.0, "auto": 10.0}
KHATA_LIMIT = 2500.0
LATE_FEE_BANK = 500.0
MONEYLENDER_PENALTY = 0.10
MISSES_TO_DEFAULT = 2

# how strongly the essential-cost shock passes into each category's price
PASS_THROUGH = {"groceries": 1.0, "medicine": 0.5, "fuel": 1.3,
                "eating_out": 0.6, "shopping": 0.1, "entertainment": 0.0}

# places where one agent runs one stall among many: the place stays open without them,
# and only this share of agents' spending goes to their stall (when they are there)
MULTI_VENDOR = {"market": 0.25}

# owner-run businesses: margin on sales, fixed daily cost, background (non-agent) sales
BUSINESS = {
    "kirana": dict(margin=0.14, fixed=300.0, background=5200.0, demand_sens=0.3),
    "cafe": dict(margin=0.35, fixed=900.0, background=3600.0, demand_sens=1.2),
    "market": dict(margin=0.25, fixed=150.0, background=2600.0, demand_sens=0.4),
}


@dataclass
class Outcome:
    """What happened when an agent tried to do something. Becomes memory and UI text."""
    ok: bool
    text: str
    importance: int = 3
    amount: float = 0.0
    data: dict = field(default_factory=dict)


class TownEconomy:
    def __init__(self, shock: Shock, seed: int = 7, start_weekday: int = 0,
                 headlines: Optional[List[str]] = None, days: int = 30,
                 onset_day: int = SHOCK_ONSET_DAY, ramp_days: int = SHOCK_RAMP_DAYS,
                 rules: Optional[Rules] = None):
        self.base_shock = shock
        self.rules = rules or Rules()
        self.damage_done = False
        self.onset_day = max(1, onset_day)
        self.ramp_days = max(1, ramp_days)
        self.rng = random.Random(seed * 7919 + 13)
        self.start_weekday = start_weekday
        self.days = days
        self.day = 1
        self.sales_today: Dict[str, float] = {}           # place -> ₹ from agents today
        self.sales_history: Dict[str, List[float]] = {}   # place -> daily total (agents + background)
        self.owner_present: Dict[Tuple[str, str], bool] = {}  # (place, phase) -> owner at shop
        self.work_offered: Dict[Tuple[str, str], bool] = {}   # (agent, day) -> shift available
        self.layoffs_done = False
        self.news: Dict[int, List[str]] = {}
        self._schedule_news(headlines or [])

    # ── shock timeline ──────────────────────────────────────────────────────
    def shock_for(self, day: Optional[int] = None) -> Shock:
        """The shock in force on a day: the base shock, or a blend into the later one (boom, then bust)."""
        d = self.day if day is None else day
        shift = self.rules.shift
        if shift is None:
            return self.base_shock
        start, length, target = shift
        s = max(0.0, min(1.0, (d - (self.layoff_day + start) + 1) / max(1, length)))
        if s <= 0:
            return self.base_shock
        a, b = self.base_shock, target
        return Shock(**{k: getattr(a, k) + (getattr(b, k) - getattr(a, k)) * s for k in Shock.__dataclass_fields__})

    @property
    def shock(self) -> Shock:
        return self.shock_for()

    def ramp(self, day: Optional[int] = None) -> float:
        d = self.day if day is None else day
        if self.base_shock.is_zero or d < self.onset_day:
            return 0.0
        return min(1.0, (d - self.onset_day + 1) / self.ramp_days)

    def _schedule_news(self, headlines: List[str]) -> None:
        if not headlines or self.base_shock.is_zero:
            return
        self.news.setdefault(self.onset_day, []).append(headlines[0])
        gap = 1 if self.ramp_days <= 4 else 2
        for i, h in enumerate(headlines[1:8]):
            self.news.setdefault(self.onset_day + 1 + i * gap, []).append(h)

    @property
    def layoff_day(self) -> int:
        """Job cuts come when the shock reaches its full effect."""
        return self.onset_day + self.ramp_days - 1

    def add_news(self, day: int, headline: str) -> None:
        self.news.setdefault(day, []).append(headline)

    def weekday(self, day: Optional[int] = None) -> str:
        return weekday_of(self.day if day is None else day, self.start_weekday)

    # ── scenario rules: lockdown, closures, rationing, disaster damage ───────
    def lockdown_active(self, day: Optional[int] = None) -> bool:
        d = self.day if day is None else day
        return self.rules.lockdown and d >= self.onset_day

    def _closed_by_rules(self, place: Place, day: int) -> str:
        """Why a place is shut by the scenario (not by the calendar); empty if it is not."""
        if self.lockdown_active(day) and place.kind != "home" and place.id not in self.rules.essential:
            return "closed during the lockdown"
        for pid, first, last in self.rules.closures:
            if pid == place.id and self.onset_day + first <= day <= self.onset_day + last:
                return "closed after the disaster"
        return ""

    def place_open(self, place: Place, day: Optional[int] = None) -> bool:
        d = self.day if day is None else day
        return place.is_open(self.weekday(d)) and not self._closed_by_rules(place, d)

    def closed_reason(self, place: Place) -> str:
        if not place.is_open(self.weekday()):
            return f"closed on {self.weekday()}s"
        return self._closed_by_rules(place, self.day)

    def access_blocked(self, place: Place) -> bool:
        """In a lockdown nobody may go anywhere but home and the essential places."""
        return self.lockdown_active() and place.kind != "home" and place.id not in self.rules.essential

    def restrictions_today(self) -> Tuple[bool, Tuple[str, ...]]:
        """What is restricted today (to notice changes between days)."""
        shut = tuple(sorted(p.id for p in PLACES.values() if self._closed_by_rules(p, self.day)))
        return self.lockdown_active(), shut

    def ration_factor(self, category: str) -> float:
        """Share of the usual stock still on sale; it shrinks as the shock builds."""
        r = self.rules.ration_for(category)
        return 1.0 - (1.0 - r) * self.ramp()

    def rules_text(self) -> List[str]:
        """What is different today, for the agents' prompt."""
        out = []
        if self.lockdown_active():
            names = ", ".join(PLACES[p].name for p in self.rules.essential)
            out.append(f"STRICT LOCKDOWN: you must stay at home. The only places you may go to are {names}. "
                       "Offices, factories, schools, markets, the bank and all other places are shut. "
                       "Office staff and students work and study from home; daily-wage workers, drivers and shopkeepers "
                       "whose places are shut earn nothing.")
        shut = sorted(PLACES[pid].name for pid, first, last in self.rules.closures
                      if self.onset_day + first <= self.day <= self.onset_day + last)
        if shut:
            out.append("Shut today because of the disaster: " + ", ".join(shut))
        for cat, _ in self.rules.ration:
            f = self.ration_factor(cat)
            if f < 0.95:
                out.append(f"{cat.replace('_', ' ').capitalize()} is rationed: shops sell only about {f:.0%} of the usual stock, so you cannot stock up")
        return out

    def disaster_losses(self, agents: Dict[str, Agent]) -> List[Tuple[Agent, Outcome]]:
        """A one-off repair bill for people whose homes were damaged."""
        dmg = self.rules.damage
        if dmg is None or self.damage_done or self.day != self.onset_day + dmg[2]:
            return []
        self.damage_done = True
        homes, amount, _ = dmg
        out = []
        for a in agents.values():
            if a.home in homes:
                lost = min(a.money, amount)
                a.money -= lost
                out.append((a, Outcome(False, f"The flood damaged my home; repairs cost ₹{lost:,.0f}", 10, amount=lost)))
        return out

    # ── prices ──────────────────────────────────────────────────────────────
    def price_multiplier(self, category: str, day: Optional[int] = None) -> float:
        m = 1.0 + PASS_THROUGH.get(category, 0.0) * self.shock_for(day).essential_cost * self.ramp(day)
        return max(0.4, m)   # prices can fall a long way, but not to nothing

    def price_at(self, place: Place, category: str, day: Optional[int] = None) -> float:
        return place.price_index * self.price_multiplier(category, day)

    def price_board(self) -> Dict[str, float]:
        """Town-wide price index per category (1.00 = before the shock)."""
        return {c: round(self.price_multiplier(c), 3) for c in PASS_THROUGH}

    def fuel_price(self) -> float:
        return round(FUEL_PRICE_PER_LITRE * self.price_multiplier("fuel"), 1)

    # ── shops ───────────────────────────────────────────────────────────────
    def owner_of(self, place_id: str, agents: Dict[str, Agent]) -> Optional[Agent]:
        for a in agents.values():
            if a.pay_type == "business" and a.workplace == place_id:
                return a
        return None

    def shop_open(self, place: Place, phase: str, agents: Dict[str, Agent]) -> Tuple[bool, str]:
        if not self.place_open(place):
            return False, f"{place.name} is {self.closed_reason(place)}"
        if place.id in BUSINESS and place.id not in MULTI_VENDOR and self.owner_of(place.id, agents) is not None:
            if not self.owner_present.get((place.id, phase), False):
                return False, f"{place.name} was shut — the owner wasn't there"
        return True, ""

    def buy(self, agent: Agent, place: Place, category: str, amount: float,
            owner: Optional[Agent] = None, phase: Optional[str] = None) -> Outcome:
        if amount <= 0:
            return Outcome(True, "", 1)
        mult = self.price_at(place, category)
        cap = self._purchase_cap(agent, category, mult)
        rationed = self.ration_factor(category) < 0.95
        capped = False
        if cap is not None and amount > cap:
            amount = cap
            capped = True
            if amount <= 1:
                if rationed:
                    return Outcome(False, f"Couldn't buy more {category.replace('_', ' ')} at {place.name}: supplies are rationed "
                                          "and my share was already taken", 7)
                return Outcome(False, f"Didn't need more {category.replace('_', ' ')} — already stocked up", 2)
        on_credit = 0.0
        if amount > agent.money:
            shortfall = amount - agent.money
            can_khata = (place.id == "kirana" and owner is not None and owner.id in agent.knows
                         and agent.khata_due + shortfall <= KHATA_LIMIT and category == "groceries")
            if can_khata:
                on_credit = shortfall
            else:
                amount = max(0.0, agent.money)
        if amount <= 0:
            return Outcome(False, f"Could not afford {category.replace('_', ' ')} at {place.name}", 7)

        agent.money -= amount - on_credit
        agent.khata_due += on_credit
        agent.spent[category] = agent.spent.get(category, 0.0) + amount
        share = 1.0
        if place.id in MULTI_VENDOR:
            share = MULTI_VENDOR[place.id] if self.owner_present.get((place.id, phase), phase is None) else 0.0
        self.sales_today[place.id] = self.sales_today.get(place.id, 0.0) + amount * share

        if category == "groceries":
            days = amount / max(1.0, agent.daily_grocery_need * mult)
            agent.pantry_days = min(PANTRY_MAX_DAYS, agent.pantry_days + days)
            what = f"₹{amount:,.0f} of groceries ({days:.1f} days' worth)"
        elif category == "medicine":
            per_day = max(1.0, agent.medicine_monthly / 30.0 * mult)
            days = amount / per_day
            agent.medicine_days = min(MEDICINE_MAX_DAYS, agent.medicine_days + days)
            what = f"₹{amount:,.0f} of medicine ({days:.0f} days)"
        elif category == "fuel":
            litres = amount / (FUEL_PRICE_PER_LITRE * mult)
            per_day = max(0.1, agent.fuel_litres_per_day)
            agent.fuel_days = min(TANK_LITRES.get(agent.vehicle, 5.0) / per_day, agent.fuel_days + litres / per_day)
            what = f"{litres:.1f} L of fuel for ₹{amount:,.0f} (₹{FUEL_PRICE_PER_LITRE * mult:.0f}/L)"
        else:
            what = f"₹{amount:,.0f} on {category.replace('_', ' ')}"
        credit_note = f", ₹{on_credit:,.0f} of it on the shop's credit (khata)" if on_credit else ""
        if rationed and capped:
            credit_note += " — the shop would only sell a limited amount (rationing)"
        return Outcome(True, f"Bought {what} at {place.name}{credit_note}", 2 if category in ("groceries", "fuel") else 3,
                       amount=amount, data={"category": category, "on_credit": on_credit, "price_mult": round(mult, 3)})

    def _purchase_cap(self, agent: Agent, category: str, mult: float) -> Optional[float]:
        if category == "groceries":
            if agent.daily_grocery_need <= 0:
                return 0.0
            return max(0.0, (PANTRY_MAX_DAYS * self.ration_factor("groceries") - agent.pantry_days) * agent.daily_grocery_need * mult)
        if category == "medicine":
            if not agent.chronic_condition:
                return 400.0  # occasional over-the-counter purchase
            return max(0.0, (MEDICINE_MAX_DAYS * self.ration_factor("medicine") - agent.medicine_days) * agent.medicine_monthly / 30 * mult)
        if category == "fuel":
            if agent.fuel_litres_per_day <= 0:
                return 0.0
            tank_days = TANK_LITRES.get(agent.vehicle, 5.0) / agent.fuel_litres_per_day
            return max(0.0, (tank_days * self.ration_factor("fuel") - agent.fuel_days) * agent.fuel_litres_per_day * FUEL_PRICE_PER_LITRE * mult)
        return None

    # ── work ────────────────────────────────────────────────────────────────
    def shift_available(self, agent: Agent) -> bool:
        """Daily-wage work is offered per worker per day; it dries up when incomes are hit."""
        key = (agent.id, str(self.day))
        if key not in self.work_offered:
            if not agent.employed:
                avail = False
            elif agent.pay_type == "daily":
                base = 0.9 if agent.workplace == "construction" else 0.95
                sens = 2.2 if agent.workplace == "construction" else 1.8
                p = max(0.25, min(1.0, base + sens * self.shock.income * self.ramp()))
                avail = self.rng.random() < p
            else:
                avail = True
            self.work_offered[key] = avail
        return self.work_offered[key]

    def do_work(self, agent: Agent, phase: str) -> Outcome:
        place = PLACES.get(agent.workplace or "")
        if place is None:
            return Outcome(False, "Has no workplace to go to", 1)
        if not agent.employed:
            return Outcome(False, f"No job at {place.name} any more", 8)
        if not self.place_open(place) and agent.pay_type != "self":
            why = self.closed_reason(place)
            return Outcome(False, f"{place.name} is {why}" if "lockdown" in why or "disaster" in why else f"{place.name} is closed today",
                           7 if "lockdown" in why or "disaster" in why else 2)
        if not self.place_open(place) and agent.pay_type == "self":
            return Outcome(False, "Couldn't work: " + (self.closed_reason(place) or "no customers") + "; nobody was allowed out", 7)

        if agent.pay_type == "daily":
            if not self.shift_available(agent):
                return Outcome(False, f"No shift at {place.name} today — the supervisor sent people home", 7)
            pay = agent.pay_rate * 0.5
            agent.money += pay
            agent.earned += pay
            return Outcome(True, f"Worked the {phase} shift at {place.name}, earned ₹{pay:,.0f}", 2, amount=pay)

        if agent.pay_type == "self":
            if agent.fuel_days <= 0:
                return Outcome(False, "Couldn't work — the fuel tank is empty", 7)
            sens = 0.9 if agent.job_key == "delivery_rider" else 0.5
            demand = max(0.3, 1.0 + sens * self.shock.demand * self.ramp())
            gross = 0.5 * agent.pay_rate * demand * self.rng.uniform(0.8, 1.2)
            agent.fuel_days = max(0.0, agent.fuel_days - 0.5)
            agent.money += gross
            agent.earned += gross
            busy = "busy" if demand > 0.95 else ("slower than usual" if demand > 0.75 else "very slow")
            return Outcome(True, f"Drove the {phase} shift: earned ₹{gross:,.0f}, customers were {busy}", 3 if demand > 0.9 else 5,
                           amount=gross, data={"demand": round(demand, 2)})

        if agent.pay_type == "business":
            self.owner_present[(agent.workplace, phase)] = True
            return Outcome(True, f"Ran {place.name} in the {phase}", 1)

        # salaried: pay arrives on the 1st; attendance is still expected
        return Outcome(True, f"Worked at {place.name} in the {phase}", 1)

    def maybe_layoffs(self, agents: Dict[str, Agent]) -> List[Tuple[Agent, str]]:
        """A one-off round of job cuts if the scenario hits incomes hard."""
        if (self.layoffs_done or not self.rules.layoffs or self.base_shock.income > -0.1
                or self.day != self.layoff_day):
            return []
        self.layoffs_done = True
        p = min(0.3, (-self.base_shock.income - 0.1) * 1.2)
        cut = []
        for a in agents.values():
            if a.employed and a.workplace in ("tech_park", "factory") and a.job_key != "security_guard":
                if self.rng.random() < p:
                    a.employed = False
                    cut.append((a, PLACES[a.workplace].name))
        if cut:
            names = sorted({w for _, w in cut})
            self.add_news(self.day, f"{' and '.join(names)} announce job cuts as orders fall")
        return cut

    def business_close_of_day(self, agents: Dict[str, Agent]) -> List[Tuple[Agent, Outcome]]:
        results = []
        for pid, cfg in BUSINESS.items():
            owner = self.owner_of(pid, agents)
            from_agents = self.sales_today.get(pid, 0.0)
            open_phases = sum(1 for ph in ("morning", "afternoon", "evening") if self.owner_present.get((pid, ph)))
            if owner is None:
                open_phases = 3
            open_today = self.place_open(PLACES[pid])
            demand = max(0.2, 1.0 + cfg["demand_sens"] * self.shock.demand * self.ramp())
            background = cfg["background"] * demand * (open_phases / 3.0) * (1.0 if open_today else 0.0)
            background *= self.price_multiplier("groceries" if pid != "cafe" else "eating_out")
            total = from_agents + background
            self.sales_history.setdefault(pid, []).append(round(total, 0))
            if owner is not None:
                profit = cfg["margin"] * total - (cfg["fixed"] if open_today else 0.0)
                owner.money += profit
                owner.earned += profit
                avg = sum(self.sales_history[pid][-7:]) / len(self.sales_history[pid][-7:])
                trend = ""
                if len(self.sales_history[pid]) > 3 and total < 0.85 * avg:
                    trend = " — noticeably fewer customers than this past week"
                results.append((owner, Outcome(True, f"{PLACES[pid].name} took ₹{total:,.0f} today, profit ₹{profit:,.0f}{trend}",
                                               3 if not trend else 6, amount=profit)))
        self.sales_today = {}
        self.owner_present = {}
        return results

    # ── bank ────────────────────────────────────────────────────────────────
    def loan_terms(self) -> dict:
        t = self.shock.credit_tightness * self.ramp()
        return {"min_score": int(620 + 160 * t), "max_income_multiple": max(0.5, 3.0 - 2.0 * t),
                "max_dti": max(0.25, 0.55 - 0.25 * t), "annual_rate": round(0.13 + 0.03 * t, 4)}

    def apply_loan(self, agent: Agent, amount: float) -> Outcome:
        terms = self.loan_terms()
        monthly = max(1.0, agent.monthly_income_estimate)
        amount = round(amount, -2)
        if amount <= 0:
            return Outcome(False, "", 1)
        if agent.is_defaulted:
            return Outcome(False, "The bank refused the loan: there is a defaulted loan on record", 8)
        if agent.credit_score < terms["min_score"]:
            return Outcome(False, f"The bank refused the loan: credit score {agent.credit_score} is below the "
                                  f"{terms['min_score']} they now require", 8)
        if amount > monthly * terms["max_income_multiple"]:
            return Outcome(False, f"The bank refused ₹{amount:,.0f}: the most they lend now is "
                                  f"₹{monthly * terms['max_income_multiple']:,.0f}", 7)
        r = terms["annual_rate"] / 12
        emi = round(amount * r * (1 + r) ** 12 / ((1 + r) ** 12 - 1), -1)
        dti = (self.monthly_emis(agent) + emi) / monthly
        if dti > terms["max_dti"]:
            return Outcome(False, f"The bank refused the loan: EMIs would take {dti:.0%} of income "
                                  f"(limit {terms['max_dti']:.0%})", 7)
        agent.loans.append(Loan("personal", "bank", amount, emi, "monthly", self.day, taken_day=self.day))
        agent.money += amount
        return Outcome(True, f"The bank approved a ₹{amount:,.0f} personal loan at {terms['annual_rate']:.1%}; "
                             f"EMI ₹{emi:,.0f} a month", 8, amount=amount)

    def moneylender(self, agent: Agent, amount: float) -> Outcome:
        amount = round(min(amount, 15000.0), -2)
        if amount <= 0:
            return Outcome(False, "", 1)
        weekly = round(amount * 0.08, -1)
        agent.loans.append(Loan("moneylender", "moneylender", amount, weekly, "weekly",
                                (self.start_weekday + self.day - 1) % 7 + 1, taken_day=self.day))
        agent.money += amount
        return Outcome(True, f"Borrowed ₹{amount:,.0f} from the moneylender; ₹{weekly:,.0f} due every week", 8, amount=amount)

    def repay_extra(self, agent: Agent, amount: float) -> Outcome:
        amount = min(amount, agent.money)
        if amount <= 0 or not agent.loans:
            return Outcome(False, "", 1)
        # costliest debt first
        order = sorted([l for l in agent.loans if l.outstanding > 0],
                       key=lambda l: (l.lender != "moneylender", l.kind != "credit_card"))
        paid = 0.0
        for loan in order:
            take = min(loan.outstanding, amount - paid)
            loan.outstanding -= take
            paid += take
            if paid >= amount:
                break
        agent.money -= paid
        agent.loans = [l for l in agent.loans if l.outstanding > 1]
        return Outcome(True, f"Paid ₹{paid:,.0f} extra towards loans", 5, amount=paid)

    def monthly_emis(self, agent: Agent) -> float:
        return sum(l.emi * (4.3 if l.frequency == "weekly" else 1.0) for l in agent.loans)

    # ── money flows that happen on their own ────────────────────────────────
    def morning_income(self, agent: Agent) -> List[Outcome]:
        """Salary, pension and allowance arrive on the 1st (day 1 of the run)."""
        out = []
        if self.day == 1 and agent.pay_type in ("monthly", "pension", "allowance") and agent.employed:
            agent.money += agent.pay_rate
            agent.earned += agent.pay_rate
            label = {"monthly": "Salary", "pension": "Pension", "allowance": "Allowance from family"}[agent.pay_type]
            out.append(Outcome(True, f"{label} of ₹{agent.pay_rate:,.0f} arrived", 5, amount=agent.pay_rate))
        return out

    def bills_due(self, agent: Agent, within_days: int = 7) -> List[dict]:
        """Upcoming payments the agent knows about (for the prompt and the UI)."""
        items = []
        for d in range(self.day, min(self.days, self.day + within_days) + 1):
            for b in self._bills_on(agent, d):
                items.append(b)
        return items

    def _bills_on(self, agent: Agent, day: int) -> List[dict]:
        out = []
        if agent.renter and day == 5 and not agent.rent_paid and agent.rent > 0:
            out.append({"day": day, "what": "rent", "amount": agent.rent})
        if day == 10 and not agent.utility_paid and agent.utility_bill > 0:
            out.append({"day": day, "what": "electricity & phone", "amount": agent.utility_bill})
        if agent.school_fee and day == agent.school_fee_due_day and not agent.fee_paid:
            out.append({"day": day, "what": "school fees", "amount": agent.school_fee})
        wd = (self.start_weekday + day - 1) % 7 + 1
        for i, l in enumerate(agent.loans):
            if l.defaulted:
                continue
            if day - l.taken_day < (7 if l.frequency == "weekly" else 28):
                continue   # first instalment isn't due yet
            if (l.frequency == "monthly" and l.due_day == day) or (l.frequency == "weekly" and l.due_day == wd):
                out.append({"day": day, "what": f"{l.kind.replace('_', ' ')} EMI", "amount": l.emi, "loan": i})
        return out

    def settle_bills(self, agent: Agent, skip: List[str]) -> List[Outcome]:
        """Auto-debit today's bills. Skipped or unaffordable ones are missed, with consequences."""
        out = []
        skip_l = [s.lower() for s in (skip or [])]
        for bill in self._bills_on(agent, self.day):
            label = bill["what"]
            chosen_skip = any(s and (s in label or label.split()[0] in s) for s in skip_l)
            if not chosen_skip and agent.money >= bill["amount"]:
                agent.money -= bill["amount"]
                if label == "rent":
                    agent.rent_paid = True
                elif label.startswith("electricity"):
                    agent.utility_paid = True
                elif label == "school fees":
                    agent.fee_paid = True
                elif "loan" in bill:
                    loan = agent.loans[bill["loan"]]
                    loan.outstanding = max(0.0, loan.outstanding - bill["amount"] * 0.7)
                out.append(Outcome(True, f"Paid {label}: ₹{bill['amount']:,.0f}", 3, amount=bill["amount"],
                                   data={"bill": label}))
                continue
            why = "chose to hold the money back" if chosen_skip else "not enough money"
            if "loan" in bill:
                loan = agent.loans[bill["loan"]]
                loan.missed += 1
                if loan.lender == "moneylender":
                    loan.outstanding *= 1 + MONEYLENDER_PENALTY
                    agent.credit_score -= 5
                else:
                    agent.money = max(0.0, agent.money - LATE_FEE_BANK) if agent.money > LATE_FEE_BANK else agent.money
                    agent.credit_score -= 35
                if loan.missed >= MISSES_TO_DEFAULT:
                    loan.defaulted = True
                    agent.credit_score -= 120
                    out.append(Outcome(False, f"Defaulted on the {loan.kind.replace('_', ' ')} loan after missing "
                                              f"{loan.missed} payments", 10, data={"bill": label, "default": True}))
                else:
                    out.append(Outcome(False, f"Missed the {label} of ₹{bill['amount']:,.0f} ({why}); "
                                              f"credit score now {agent.credit_score}", 9, data={"bill": label}))
            else:
                out.append(Outcome(False, f"Couldn't pay {label} of ₹{bill['amount']:,.0f} ({why})", 8,
                                   data={"bill": label}))
        agent.credit_score = max(300, min(900, agent.credit_score))
        return out

    def end_of_day_consumption(self, agent: Agent, went_out: bool) -> List[Outcome]:
        out = []
        if agent.daily_grocery_need > 0:
            agent.pantry_days -= 1.0
            if agent.pantry_days < 0:
                agent.pantry_days = 0.0
                agent.days_hungry += 1
                out.append(Outcome(False, "Ran out of food at home; the family ate less today", 9))
            elif agent.pantry_days < 1.5:
                out.append(Outcome(False, "Almost out of groceries at home", 6))
        if agent.chronic_condition:
            agent.medicine_days -= 1.0
            if agent.medicine_days < 0:
                agent.medicine_days = 0.0
                agent.days_without_medicine += 1
                out.append(Outcome(False, f"Out of medicine for {agent.chronic_condition}; felt unwell", 9))
        if went_out and agent.vehicle in ("scooter", "car") and agent.job_key != "delivery_rider":
            agent.fuel_days = max(0.0, agent.fuel_days - 1.0)
            if agent.fuel_days <= 0:
                fare = 60.0
                agent.money = max(0.0, agent.money - fare)
                out.append(Outcome(False, f"The {agent.vehicle} is out of fuel; paid ₹{fare:.0f} for the bus", 5))
        return out

    def advance(self) -> None:
        self.day += 1
