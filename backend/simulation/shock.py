"""
shock.py — the numeric "shock" a scenario applies to the simulated economy.

Why this module exists
----------------------
A scenario is first turned into a causal chain (module 3), and each chain node
is mapped to four numeric deltas by the Semantic-to-Numerical Mapper (module 6):

    discretionary_spend_pct, savings_rate_pct,
    essential_cost_index_pct, credit_availability_pct

Those deltas used to stop at the macro state's starting values, which agents
only saw as small observation changes — the shock never reached anyone's
budget. This module collapses a chain's deltas into ONE `Shock` that EcoSimEnv
applies to every agent's budget on every tick (see EcoSimEnv.step).

Modelling assumptions (documented, deliberately simple and inspectable)
-----------------------------------------------------------------------
* Deltas are SUMMED across nodes, then clamped to +/-MAX_SHOCK, because later
  nodes are knock-on effects of earlier ones and an unbounded sum would let a
  long chain dominate everything.
* essential_cost  = sum(essential_cost_index_pct)       -> essentials get dearer
* demand          = sum(discretionary_spend_pct)        -> appetite/utility of spending
* income          = INCOME_PASS_THROUGH * demand        -> weak demand squeezes incomes
* credit_tightness= -sum(credit_availability_pct)       -> debt becomes harder to carry
* savings         = sum(savings_rate_pct)               -> precautionary-saving mood

A zero Shock reproduces the original (shock-free) dynamics exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

import numpy as np

MAX_SHOCK = 0.6            # clamp for every component
INCOME_PASS_THROUGH = 0.5  # how much of a demand shock reaches incomes

# Baseline macro state (RBI-era values) — same numbers simulate.py always used.
BASE_INFLATION = 5.5
BASE_REPO = 6.5
BASE_FUEL = 110.0


@dataclass(frozen=True)
class Shock:
    essential_cost: float = 0.0     # +0.3  -> essentials cost 30% more
    income: float = 0.0             # -0.1  -> incomes 10% lower
    credit_tightness: float = 0.0   # +0.3  -> credit much tighter (negative = looser)
    demand: float = 0.0             # -0.3  -> consumers cut discretionary spending
    savings: float = 0.0            # +0.2  -> stronger precautionary saving

    @property
    def is_zero(self) -> bool:
        return all(abs(v) < 1e-12 for v in asdict(self).values())

    def to_dict(self) -> Dict[str, float]:
        return {k: round(float(v), 4) for k, v in asdict(self).items()}

    def as_obs(self) -> np.ndarray:
        """The three shock features agents can perceive (§7.1 'perceived macro shocks')."""
        return np.array([self.essential_cost, self.income, self.credit_tightness],
                        dtype=np.float32)

    @classmethod
    def from_any(cls, value: Any) -> "Shock":
        if value is None:
            return cls()
        if isinstance(value, Shock):
            return value
        if isinstance(value, dict):
            return cls(**{k: float(v) for k, v in value.items() if k in cls.__dataclass_fields__})
        raise TypeError(f"Cannot build a Shock from {type(value).__name__}")


def _clamp(x: float) -> float:
    return float(max(-MAX_SHOCK, min(MAX_SHOCK, x)))


def _node_deltas(node: Any) -> Dict[str, float]:
    deltas = node.get("deltas", {}) if isinstance(node, dict) else getattr(node, "deltas", {})
    if not isinstance(deltas, dict):
        deltas = {k: getattr(deltas, k, 0.0) for k in (
            "discretionary_spend_pct", "savings_rate_pct",
            "essential_cost_index_pct", "credit_availability_pct")}
    return {k: float(deltas.get(k, 0.0) or 0.0) for k in (
        "discretionary_spend_pct", "savings_rate_pct",
        "essential_cost_index_pct", "credit_availability_pct")}


def shock_from_deltas(mapped_nodes: Iterable[Any]) -> Shock:
    """Collapse per-node mapper deltas into one Shock. Nodes without deltas count as zero."""
    disc = sav = ess = cred = 0.0
    for node in mapped_nodes or []:
        d = _node_deltas(node)
        disc += d["discretionary_spend_pct"]
        sav += d["savings_rate_pct"]
        ess += d["essential_cost_index_pct"]
        cred += d["credit_availability_pct"]
    demand = _clamp(disc)
    return Shock(
        essential_cost=_clamp(ess),
        income=_clamp(INCOME_PASS_THROUGH * demand),
        credit_tightness=_clamp(-cred),
        demand=demand,
        savings=_clamp(sav),
    )


def macro_from_shock(shock: Shock) -> Dict[str, float]:
    """Starting macro state implied by a shock (same mapping simulate.py always used)."""
    inflation = BASE_INFLATION + shock.essential_cost * 3.0
    repo = BASE_REPO + shock.credit_tightness * 2.0
    fuel = BASE_FUEL + shock.demand * 5.0
    return {
        "inflation_rate": max(0.0, min(25.0, inflation)),
        "repo_rate": max(0.0, min(20.0, repo)),
        "fuel_price_index": max(50.0, min(250.0, fuel)),
    }


def sample_random_shock(rng: np.random.Generator) -> Shock:
    """
    A random scenario-like shock for TRAINING, so policies learn to respond to
    shocks instead of memorising one. ~25% of episodes are shock-free so calm
    conditions are learned too.
    """
    if rng.random() < 0.25:
        return Shock()
    essential = float(rng.uniform(0.0, 0.5))
    demand = float(rng.uniform(-0.5, 0.1))
    credit = float(rng.uniform(-0.1, 0.5))
    savings = float(rng.uniform(-0.2, 0.3))
    return Shock(
        essential_cost=essential,
        income=INCOME_PASS_THROUGH * demand,
        credit_tightness=credit,
        demand=demand,
        savings=savings,
    )


# Named presets used by evaluate_policy.py and tests.
PRESETS: Dict[str, Shock] = {
    "none": Shock(),
    "mild": Shock(essential_cost=0.15, income=-0.05, credit_tightness=0.15,
                  demand=-0.10, savings=0.05),
    "severe": Shock(essential_cost=0.45, income=-0.2, credit_tightness=0.4,
                    demand=-0.4, savings=0.15),
}


def describe(shock: Optional[Shock]) -> str:
    if shock is None or shock.is_zero:
        return "no shock"
    return ", ".join(f"{k}={v:+.2f}" for k, v in shock.to_dict().items() if abs(v) > 1e-9)
