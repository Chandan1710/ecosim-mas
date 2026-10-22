"""
scenarios.py — the ready-made scenarios offered on the home page.

Seven scenarios plus "describe your own" in the UI. These live here, not in simulation/shock.py,
so adding town scenarios does not change the RL baseline's evaluation sweep (evaluate_policy.py
loops over every shock.PRESETS entry).

A scenario is a Shock (the numeric squeeze on prices, incomes and credit; see simulation/shock.py,
positive credit_tightness means harder to borrow) plus optional Rules for things a single shock
vector cannot say:

  lockdown   everyone must stay home except for essential shops and the clinic
  shift      the shock turns into a different one part-way (boom, then bust)
  closures   named places shut for a few days (disaster damage)
  damage     a one-off repair bill for people living in named homes
  ration     shops only sell part of the usual stock of a category (scarcity)

Closure and damage day offsets are counted from the day the shock begins (day 0 = onset day). A
shift starts after the first shock has reached full strength, so the boom is seen before the bust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from simulation.shock import Shock

ESSENTIAL_PLACES = ("kirana", "supermarket", "pharmacy", "clinic")


@dataclass(frozen=True)
class Rules:
    lockdown: bool = False
    essential: Tuple[str, ...] = ESSENTIAL_PLACES            # places that stay open in a lockdown
    shift: Optional[Tuple[int, int, Shock]] = None           # (starts N days after full strength, takes N days, new shock)
    closures: Tuple[Tuple[str, int, int], ...] = ()          # (place, first day offset, last day offset)
    damage: Optional[Tuple[Tuple[str, ...], float, int]] = None   # (homes, rupees lost, day offset)
    ration: Tuple[Tuple[str, float], ...] = ()               # (category, share of normal stock still on sale)
    layoffs: bool = True                                     # a hard income shock also cuts factory/office jobs

    def ration_for(self, category: str) -> float:
        return dict(self.ration).get(category, 1.0)

    def tags(self) -> List[str]:
        """Short labels for the scenario card."""
        out = []
        if self.lockdown:
            out.append("Stay-at-home order")
        if self.shift:
            out.append("Boom, then bust")
        if self.closures:
            out.append("Places shut")
        if self.damage:
            out.append("Home repairs")
        if self.ration:
            out.append("Rationing")
        return out

    def describe(self) -> List[str]:
        out = []
        if self.lockdown:
            out.append("Strict lockdown: everyone must stay at home; only the grocery shops, the pharmacy and the clinic stay open")
        if self.shift:
            out.append("Prices spiral upward first; later they collapse as demand dries up")
        if self.closures:
            out.append("Damaged places are shut for a few days: " + ", ".join(sorted({c[0] for c in self.closures})))
        if self.damage:
            out.append("Homes in some neighbourhoods need costly repairs")
        for cat, share in self.ration:
            out.append(f"{cat.replace('_', ' ').capitalize()} is rationed: only about {share:.0%} of the usual stock is on sale")
        return out


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    blurb: str
    shock: Shock
    headlines: Tuple[str, ...] = ()
    rules: Rules = field(default_factory=Rules)


_LIST = [
    Scenario(
        "severe", "Severe fuel and credit shock",
        "Crude oil jumps 30% after a supply shock. Petrol, transport and food get dearer while banks tighten loans.",
        Shock(essential_cost=0.45, income=-0.2, credit_tightness=0.4, demand=-0.4, savings=0.15),
        ("Crude oil jumps 30% after a supply shock; petrol up sharply across the state",
         "Transport costs surge; vegetable and grain prices climb at local markets",
         "Restaurants and malls report fewer customers as households cut back",
         "Banks tighten personal-loan approvals as defaults rise",
         "Factories slow production as orders fall"),
    ),
    Scenario(
        "pandemic", "Deadly pandemic and crop failure",
        "A deadly plant disease wipes out rice and wheat for good. Food becomes scarce and ruinously dear.",
        Shock(essential_cost=0.9, income=-0.2, credit_tightness=0.3, demand=-0.3, savings=0.2),
        ("A deadly outbreak is spreading through the region's rice and wheat fields; whole harvests are lost",
         "Scientists warn the infected crops cannot be grown again; rice and wheat prices double in the market",
         "Shops start limiting how much grain and flour each family can buy",
         "Hospitals fill up and medicines run short as the sickness spreads",
         "Families cut every other expense to afford food"),
        Rules(ration=(("groceries", 0.15), ("medicine", 0.6))),
    ),
    Scenario(
        "war", "World war between several countries",
        "Fighting breaks out between major powers. Fuel and food imports are cut off and the economy seizes up.",
        Shock(essential_cost=0.55, income=-0.25, credit_tightness=0.45, demand=-0.35, savings=0.2),
        ("War breaks out between several major countries; oil and shipping routes are cut",
         "Petrol pumps run dry; the government begins rationing fuel",
         "Imported goods vanish from shelves and food prices climb daily",
         "Banks freeze new lending as markets crash",
         "Factories close as supplies and export orders vanish"),
        Rules(ration=(("fuel", 0.3), ("groceries", 0.6), ("medicine", 0.7))),
    ),
    Scenario(
        "disaster", "Natural disasters",
        "Floods and storms damage homes and roads. The market, school, construction site and park shut for days.",
        Shock(essential_cost=0.2, income=-0.12, credit_tightness=0.15, demand=-0.15, savings=0.1),
        ("Heavy floods hit the town overnight; low-lying streets are under water",
         "Roads are blocked; the market, school and construction site shut until the water drains",
         "Hundreds of families need repairs; relief camps open near the lake",
         "Vegetable and milk prices rise as supply trucks are held up",
         "Banks extend loan deadlines but few new loans are approved"),
        Rules(closures=(("market", 0, 3), ("school", 0, 3), ("construction", 0, 4), ("park", 0, 5), ("factory", 0, 2)),
              damage=(("labour_colony", "old_town"), 4000.0, 0),
              layoffs=False),
    ),
    Scenario(
        "hyperinflation", "Hyperinflation and extreme deflation",
        "Prices explode as the currency loses value. Then the bubble bursts: prices collapse, jobs vanish and credit freezes.",
        Shock(essential_cost=1.2, income=-0.1, credit_tightness=0.1, demand=0.05, savings=-0.1),
        ("The rupee tumbles; shopkeepers change their prices twice a day",
         "Groceries cost double what they did last week and wages cannot keep up",
         "Panic buying empties shelves; people rush to turn cash into goods",
         "The bubble bursts: prices stop rising, then start to fall, but nobody has money to buy",
         "Shops slash prices and still stand empty; banks refuse almost all loans"),
        Rules(shift=(1, 2, Shock(essential_cost=-0.35, income=-0.3, credit_tightness=0.6, demand=-0.5, savings=0.3))),
    ),
    Scenario(
        "none", "Baseline scenario",
        "An ordinary month: prices, wages and credit stay normal. The control run to compare everything against.",
        Shock(),
    ),
    Scenario(
        "lockdown", "Emergency strict lockdown",
        "Everyone must stay inside their homes. Only grocery shops, the pharmacy and the clinic stay open.",
        Shock(essential_cost=0.12, income=-0.3, credit_tightness=0.2, demand=-0.5, savings=0.2),
        ("Emergency declared: a strict lockdown begins at once; nobody may leave home except for essentials",
         "Offices, factories, schools, the mall and the market shut; only grocery shops and the pharmacy stay open",
         "Daily-wage workers and drivers have no work and no pay",
         "Queues form outside the grocery shops as families stock up",
         "Police patrol the streets; the lockdown is extended"),
        Rules(lockdown=True, layoffs=False),
    ),
]

SCENARIOS: Dict[str, Scenario] = {s.id: s for s in _LIST}
SCENARIO_ORDER: List[str] = [s.id for s in _LIST]
TITLES: Dict[str, str] = {s.id: s.title for s in _LIST}
HEADLINES: Dict[str, List[str]] = {s.id: list(s.headlines) for s in _LIST}
