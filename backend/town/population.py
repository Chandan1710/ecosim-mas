"""
population.py — a synthetic population of unique individuals.

There are no persona templates. Each agent is sampled attribute by attribute
(job, pay, age, household, home, rent, vehicle, health, loans, savings, news
habits, relationships) from distributions loosely based on an Indian city.
Behavioural differences have to come from each agent's own circumstances,
memories and reasoning, not from a label.

Everything is seeded, so the same seed always gives the same town.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from town.world import PLACES

# ── job catalogue: facts about jobs, not about people ───────────────────────
# pay: monthly | daily | self (daily gross, variable) | business (shop profit) | pension | allowance
JOBS = [
    dict(key="software_engineer", title="software engineer at TechPark", work="tech_park", pay="monthly",
         income=(55000, 140000), age=(24, 42), homes=("lake_view", "shanti_apts"), weight=2.5, cap=3),
    dict(key="support_associate", title="customer support associate at TechPark", work="tech_park", pay="monthly",
         income=(19000, 32000), age=(21, 33), homes=("shanti_apts", "old_town", "labour_colony"), weight=1.5, cap=2),
    dict(key="garment_tailor", title="tailor at the Garment Factory", work="factory", pay="daily",
         income=(550, 750), age=(20, 52), homes=("labour_colony", "old_town"), weight=2.0, cap=3),
    dict(key="construction_labourer", title="labourer at the Metro Construction Site", work="construction", pay="daily",
         income=(500, 700), age=(19, 50), homes=("labour_colony",), weight=1.5, cap=2),
    dict(key="auto_driver", title="auto-rickshaw driver", work="auto_stand", pay="self",
         income=(800, 1400), age=(25, 58), homes=("old_town", "labour_colony"), weight=1.3, cap=2),
    dict(key="delivery_rider", title="food delivery rider", work="auto_stand", pay="self",
         income=(650, 1150), age=(19, 34), homes=("labour_colony", "old_town"), weight=1.3, cap=2),
    dict(key="kirana_owner", title="owner of Ravi Kirana Store", work="kirana", pay="business",
         income=(0, 0), age=(35, 62), homes=("old_town",), weight=0.8, cap=1),
    dict(key="cafe_owner", title="owner of Corner Café", work="cafe", pay="business",
         income=(0, 0), age=(28, 52), homes=("shanti_apts", "old_town"), weight=0.8, cap=1),
    dict(key="vegetable_vendor", title="vegetable vendor at Sabzi Market", work="market", pay="business",
         income=(0, 0), age=(25, 62), homes=("labour_colony", "old_town"), weight=1.0, cap=1),
    dict(key="teacher", title="teacher at the Government School", work="school", pay="monthly",
         income=(28000, 46000), age=(26, 58), homes=("shanti_apts", "old_town"), weight=1.5, cap=2),
    dict(key="nurse", title="nurse at the Community Clinic", work="clinic", pay="monthly",
         income=(24000, 34000), age=(23, 50), homes=("shanti_apts", "old_town"), weight=1.0, cap=1),
    dict(key="bank_clerk", title="clerk at the Town Cooperative Bank", work="bank", pay="monthly",
         income=(38000, 56000), age=(25, 56), homes=("shanti_apts", "lake_view"), weight=0.8, cap=1),
    dict(key="security_guard", title="security guard at TechPark", work="tech_park", pay="monthly",
         income=(14000, 18500), age=(24, 58), homes=("labour_colony",), weight=1.0, cap=1),
    dict(key="domestic_worker", title="domestic worker in Shanti Nagar homes", work="shanti_apts", pay="monthly",
         income=(9000, 14500), age=(24, 56), homes=("labour_colony",), weight=1.0, cap=1),
    dict(key="retired_clerk", title="retired government clerk", work=None, pay="pension",
         income=(18000, 36000), age=(61, 76), homes=("old_town", "shanti_apts"), weight=1.0, cap=2),
    dict(key="college_student", title="college student", work="school", pay="allowance",
         income=(6000, 12000), age=(18, 22), homes=("shanti_apts", "old_town", "lake_view"), weight=1.0, cap=2),
]
JOB_BY_KEY = {j["key"]: j for j in JOBS}

FIRST_M = ["Arjun", "Ravi", "Suresh", "Manoj", "Imran", "Karthik", "Vikram", "Ramesh", "Anil", "Prakash",
           "Farhan", "Naveen", "Siddharth", "Ganesh", "Joseph", "Harish", "Mahesh", "Rahul", "Deepak", "Yusuf"]
FIRST_F = ["Priya", "Lakshmi", "Anjali", "Meena", "Fatima", "Kavya", "Sunita", "Divya", "Rekha", "Asha",
           "Shabana", "Pooja", "Nandini", "Geeta", "Mary", "Swati", "Radha", "Sneha", "Zoya", "Bhavana"]
SURNAMES = ["Sharma", "Reddy", "Kumar", "Naidu", "Khan", "Iyer", "Patil", "Gowda", "Das", "Singh",
            "Fernandes", "Rao", "Shetty", "Pillai", "Ansari", "Hegde", "Yadav", "Murthy", "Joshi", "Thomas"]
VILLAGES = ["Kolar", "Raichur", "Gulbarga", "Bidar", "Anantapur", "Dharwad", "Mandya", "Tumkur"]

BASKET_PER_PERSON = {"low": 70.0, "mid": 95.0, "high": 125.0}  # ₹/person/day of groceries at price index 1


@dataclass
class Loan:
    kind: str                 # home | vehicle | personal | credit_card | moneylender | education
    lender: str               # bank | moneylender
    outstanding: float
    emi: float                # amount due each period
    frequency: str            # monthly | weekly
    due_day: int              # day-of-month (monthly) or 1-7 weekday index (weekly)
    missed: int = 0
    defaulted: bool = False
    taken_day: int = -100     # run day the loan was taken (pre-existing loans: long ago)

    def describe(self) -> str:
        when = f"due on day {self.due_day} each month" if self.frequency == "monthly" else "due every week"
        return f"{self.kind.replace('_', ' ')} from the {self.lender}: ₹{self.emi:,.0f} {when}, ₹{self.outstanding:,.0f} left"


@dataclass
class Agent:
    # who they are (fixed for the run)
    id: str
    name: str
    age: int
    gender: str
    job_key: str
    job_title: str
    workplace: Optional[str]
    pay_type: str
    pay_rate: float               # ₹/month for monthly/pension/allowance; ₹/day for daily/self
    home: str
    household_size: int
    children: int
    renter: bool
    rent: float
    vehicle: str                  # none | bicycle | scooter | car | auto
    chronic_condition: Optional[str]
    medicine_monthly: float
    reads_news: bool
    migrant_from: Optional[str]
    remittance_target: float
    school_fee: float
    school_fee_due_day: int
    utility_bill: float
    groceries_covered: bool = False   # lives with family who buy the household groceries
    loans: List[Loan] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    knows: Dict[str, str] = field(default_factory=dict)   # agent_id -> relation

    # live state (changes every day)
    money: float = 0.0
    pantry_days: float = 4.0
    fuel_days: float = 3.0
    medicine_days: float = 15.0
    credit_score: int = 720
    khata_due: float = 0.0
    employed: bool = True
    location: str = ""
    rent_paid: bool = False
    fee_paid: bool = False
    remitted: float = 0.0
    utility_paid: bool = False
    days_hungry: int = 0
    days_without_medicine: int = 0
    days_worked: int = 0
    earned: float = 0.0
    spent: Dict[str, float] = field(default_factory=dict)

    @property
    def income_tier(self) -> str:
        m = self.monthly_income_estimate
        return "low" if m < 22000 else ("mid" if m < 60000 else "high")

    @property
    def monthly_income_estimate(self) -> float:
        if self.pay_type in ("daily", "self"):
            return self.pay_rate * 26
        if self.pay_type == "business":
            return {"kirana_owner": 38000, "cafe_owner": 45000, "vegetable_vendor": 16000}.get(self.job_key, 20000)
        return self.pay_rate

    @property
    def daily_grocery_need(self) -> float:
        if self.groceries_covered:
            return 0.0
        return BASKET_PER_PERSON[self.income_tier] * self.household_size

    @property
    def fuel_litres_per_day(self) -> float:
        base = {"none": 0.0, "bicycle": 0.0, "scooter": 0.5, "car": 1.6, "auto": 4.0}[self.vehicle]
        if self.job_key == "delivery_rider":
            base = 2.5
        return base

    @property
    def is_defaulted(self) -> bool:
        return any(l.defaulted for l in self.loans)

    def bio(self) -> str:
        """Plain facts the agent knows about itself (no personality labels)."""
        pay = {
            "monthly": f"earns ₹{self.pay_rate:,.0f} a month, paid on the 1st",
            "daily": f"earns ₹{self.pay_rate:,.0f} for each day there is work",
            "self": f"makes around ₹{self.pay_rate:,.0f} a day before fuel, depending on how many customers there are",
            "business": "lives on the shop's daily profit",
            "pension": f"gets a pension of ₹{self.pay_rate:,.0f} a month on the 1st",
            "allowance": f"gets ₹{self.pay_rate:,.0f} a month from family on the 1st",
        }[self.pay_type]
        household = "lives alone" if self.household_size == 1 else f"supports a household of {self.household_size}"
        if self.children:
            household += f" including {self.children} school-going child{'ren' if self.children > 1 else ''}"
        parts = [f"{self.name}, {self.age}, {self.job_title}; {pay}"
                 + ("." if self.groceries_covered else f"; {household}.")]
        if self.migrant_from:
            parts.append(f"Family lives in {self.migrant_from} and depends on money sent home.")
        home_name = PLACES[self.home].name if self.home in PLACES else self.home
        if self.job_key == "college_student" and not self.renter:
            parts.append(f"Lives with parents in {home_name}, who pay rent, bills and household groceries.")
        elif self.job_key == "college_student":
            parts.append(f"Stays as a paying guest in {home_name} for ₹{self.rent:,.0f} a month (due on the 5th).")
        else:
            parts.append(("Rents" if self.renter else "Owns") + f" a home in {home_name}"
                         + (f" for ₹{self.rent:,.0f} a month (due on the 5th)." if self.renter else "."))
        if self.vehicle != "none":
            parts.append(f"Gets around by {self.vehicle}.")
        if self.chronic_condition:
            parts.append(f"Has {self.chronic_condition}; medicines cost about ₹{self.medicine_monthly:,.0f} a month.")
        return " ".join(parts)

    def public_state(self) -> dict:
        d = asdict(self)
        d["income_tier"] = self.income_tier
        d["monthly_income_estimate"] = self.monthly_income_estimate
        d["bio"] = self.bio()
        return d


def _emi(principal: float, annual_rate: float, months: int) -> float:
    r = annual_rate / 12.0
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def _pick_job(rng: random.Random, counts: Dict[str, int]) -> dict:
    pool = [j for j in JOBS if counts.get(j["key"], 0) < j["cap"]]
    return rng.choices(pool, weights=[j["weight"] for j in pool])[0]


def generate_population(n: int = 20, seed: int = 7) -> List[Agent]:
    rng = random.Random(seed)
    counts: Dict[str, int] = {}
    used_names = set()
    agents: List[Agent] = []

    for i in range(n):
        job = _pick_job(rng, counts)
        counts[job["key"]] = counts.get(job["key"], 0) + 1
        gender = rng.choice(("male", "female"))
        if job["key"] in ("construction_labourer", "auto_driver", "security_guard"):
            gender = "male" if rng.random() < 0.85 else "female"
        if job["key"] in ("domestic_worker", "nurse", "garment_tailor"):
            gender = "female" if rng.random() < 0.8 else "male"
        while True:
            first = rng.choice(FIRST_M if gender == "male" else FIRST_F)
            name = f"{first} {rng.choice(SURNAMES)}"
            if name not in used_names:
                used_names.add(name)
                break
        age = rng.randint(*job["age"])
        lo, hi = job["income"]
        pay_rate = round(rng.uniform(lo, hi), -2 if job["pay"] in ("monthly", "pension", "allowance") else -1)
        home = rng.choice(job["homes"])

        migrant = None
        if home == "labour_colony" and rng.random() < 0.6:
            migrant = rng.choice(VILLAGES)
        if job["key"] == "college_student":
            household = 1
        elif migrant:
            household = 1 if rng.random() < 0.7 else 2
        elif age > 60:
            household = rng.randint(1, 3)
        else:
            household = rng.randint(2, 5)
        children = 0
        if 26 <= age <= 52 and household >= 3 and job["key"] != "college_student":
            children = rng.randint(1, min(2, household - 2))

        renter = {
            "labour_colony": True, "shanti_apts": rng.random() < 0.55,
            "old_town": rng.random() < 0.3, "lake_view": rng.random() < 0.25,
        }[home]
        lives_with_parents = job["key"] == "college_student" and rng.random() < 0.5
        if job["key"] == "college_student":
            renter = not lives_with_parents       # alone = paying guest / hostel
        rent_ranges = {"labour_colony": (2800, 5000), "shanti_apts": (11000, 19000),
                       "old_town": (7000, 11000), "lake_view": (18000, 28000)}
        rent = round(rng.uniform(*rent_ranges[home]), -2) if renter else 0.0
        if job["key"] == "college_student" and renter:
            rent = round(rng.uniform(4000, 7000), -2)

        if job["key"] == "auto_driver":
            vehicle = "auto"
        elif job["key"] == "delivery_rider":
            vehicle = "scooter"
        else:
            r = rng.random()
            tier_hint = "high" if (job["pay"] == "monthly" and lo >= 50000) else ("mid" if lo >= 20000 else "low")
            if tier_hint == "high":
                vehicle = "car" if r < 0.45 else "scooter"
            elif tier_hint == "mid":
                vehicle = "scooter" if r < 0.6 else ("car" if r < 0.7 else "none")
            else:
                vehicle = "bicycle" if r < 0.3 else ("scooter" if r < 0.45 else "none")

        chronic = None
        med = 0.0
        if rng.random() < (0.65 if age > 55 else 0.15):
            chronic = rng.choice(("diabetes", "high blood pressure", "asthma", "a thyroid condition"))
            med = round(rng.uniform(600, 2800), -2)

        agent = Agent(
            id=f"a{i + 1:02d}", name=name, age=age, gender=gender, job_key=job["key"], job_title=job["title"],
            workplace=job["work"], pay_type=job["pay"], pay_rate=pay_rate, home=home,
            household_size=household, children=children, renter=renter, rent=rent, vehicle=vehicle,
            chronic_condition=chronic, medicine_monthly=med,
            reads_news=rng.random() < (0.85 if job["pay"] == "monthly" or job["key"] == "college_student" else 0.4),
            migrant_from=migrant, remittance_target=0.0, school_fee=0.0, school_fee_due_day=0,
            utility_bill=0.0, groceries_covered=lives_with_parents,
        )
        monthly = agent.monthly_income_estimate
        agent.utility_bill = 0.0 if lives_with_parents else round(max(500.0, monthly * rng.uniform(0.03, 0.06)), -1)
        if migrant:
            agent.remittance_target = round(monthly * rng.uniform(0.2, 0.35), -2)
        if children:
            agent.school_fee = round(children * (monthly * rng.uniform(0.12, 0.3)), -2)
            agent.school_fee_due_day = rng.randint(12, 20)

        # loans
        if not renter and not lives_with_parents and home in ("lake_view", "shanti_apts") and rng.random() < 0.75:
            principal = monthly * rng.uniform(40, 80)
            agent.loans.append(Loan("home", "bank", principal * 0.8, round(min(_emi(principal, 0.09, 240), monthly * 0.4), -2),
                                    "monthly", rng.randint(3, 10)))
        if vehicle in ("scooter", "car", "auto") and rng.random() < 0.5:
            price = {"scooter": 95000, "car": 750000, "auto": 320000}[vehicle]
            agent.loans.append(Loan("vehicle", "bank", price * rng.uniform(0.3, 0.7), round(_emi(price * 0.8, 0.11, 48), -2),
                                    "monthly", rng.randint(5, 15)))
        if agent.income_tier != "low" and rng.random() < 0.3:
            agent.loans.append(Loan("credit_card", "bank", monthly * rng.uniform(0.3, 1.2),
                                    round(monthly * rng.uniform(0.05, 0.1), -2), "monthly", rng.randint(15, 22)))
        if agent.income_tier == "low" and rng.random() < 0.4:
            amt = rng.choice((5000, 8000, 10000, 15000))
            agent.loans.append(Loan("moneylender", "moneylender", amt, round(amt * 0.06, -1), "weekly", rng.randint(1, 7)))

        # starting money: weeks to months of income, depending on tier
        months_saved = {"low": rng.uniform(0.15, 0.8), "mid": rng.uniform(0.5, 2.5), "high": rng.uniform(1.0, 3.5)}
        agent.money = round(monthly * months_saved[agent.income_tier], -2)
        agent.pantry_days = 30.0 if lives_with_parents else round(rng.uniform(2, 7), 1)
        agent.fuel_days = round(rng.uniform(1, 6), 1) if agent.fuel_litres_per_day else 0.0
        agent.medicine_days = round(rng.uniform(4, 25), 1) if chronic else 0.0
        agent.credit_score = max(450, min(880, int(rng.gauss(735 if agent.income_tier != "low" else 650, 45))))
        agent.employed = job["pay"] not in ("pension", "allowance")
        agent.location = home

        # goals follow from circumstances
        if migrant:
            agent.goals.append(f"Send ₹{agent.remittance_target:,.0f} home to family in {migrant} this month")
        if children:
            agent.goals.append(f"Pay ₹{agent.school_fee:,.0f} school fees by day {agent.school_fee_due_day}")
        if any(l.lender == "moneylender" for l in agent.loans):
            agent.goals.append("Clear the moneylender's loan before the interest grows")
        if agent.income_tier == "high" and age < 35:
            agent.goals.append("Save towards a home down payment")
        if age > 60:
            agent.goals.append("Never run out of medicines and keep an emergency fund")
        if job["key"] == "college_student":
            agent.goals.append("Buy a second-hand laptop for college")
        if job["pay"] == "business":
            agent.goals.append("Keep the business running through slow weeks")
        if not agent.goals:
            agent.goals.append("Build up an emergency fund")
        agents.append(agent)

    _link_relationships(agents, rng)
    return agents


def _link_relationships(agents: List[Agent], rng: random.Random) -> None:
    by_home: Dict[str, List[Agent]] = {}
    by_work: Dict[str, List[Agent]] = {}
    for a in agents:
        by_home.setdefault(a.home, []).append(a)
        if a.workplace:
            by_work.setdefault(a.workplace, []).append(a)
    for a in agents:
        neighbours = [b for b in by_home.get(a.home, []) if b.id != a.id]
        for b in rng.sample(neighbours, k=min(3, len(neighbours))):
            a.knows[b.id] = "neighbour"
            b.knows.setdefault(a.id, "neighbour")
        coworkers = [b for b in by_work.get(a.workplace or "", []) if b.id != a.id]
        for b in rng.sample(coworkers, k=min(3, len(coworkers))):
            a.knows[b.id] = "co-worker"
            b.knows.setdefault(a.id, "co-worker")
    # shopkeepers know their regulars; one random friendship each
    for a in agents:
        if a.job_key in ("kirana_owner", "cafe_owner", "vegetable_vendor"):
            for b in rng.sample(agents, k=min(3, len(agents))):
                if b.id != a.id:
                    a.knows.setdefault(b.id, "customer")
                    b.knows.setdefault(a.id, f"runs {a.workplace.replace('_', ' ')}")
        others = [b for b in agents if b.id != a.id and b.id not in a.knows]
        if others:
            b = rng.choice(others)
            a.knows[b.id] = "friend"
            b.knows.setdefault(a.id, "friend")
