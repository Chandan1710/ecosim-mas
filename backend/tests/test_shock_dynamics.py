"""
Tests for shock-driven economy dynamics (simulation/shock.py + EcoSimEnv economy mode).

No database, Ray or network needed.

What these pin down
-------------------
* A zero shock reproduces the original dynamics exactly (backward compatible).
* A scenario shock actually reaches agent budgets, and hurts thin-margin
  (low financial literacy) personas more than well-buffered ones.
* Running out of cash for INSOLVENCY_TICKS ticks forces a default and says so.
* Agents perceive the shock in their observation.
* The reward makes personas differ: for a high-spending-bias, high-risk persona
  discretionary spending pays; the default penalty makes defaulting costly.
* shock_from_deltas / macro_from_shock behave (sum, clamp, baseline).
"""

import json
import os

import numpy as np
import pytest

from simulation.ecosim_env import (
    ACTION_DEFAULT, ACTION_SAVE, ACTION_SPEND, INSOLVENCY_TICKS, OBS_DIM, make_ecosim_env,
)
from simulation.env_factory import personas_from_fixtures
from simulation.shock import (
    BASE_FUEL, BASE_INFLATION, BASE_REPO, MAX_SHOCK, PRESETS, Shock,
    macro_from_shock, sample_random_shock, shock_from_deltas,
)

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "personas.json")


@pytest.fixture(scope="module")
def personas():
    with open(_FIXTURES) as f:
        return personas_from_fixtures(json.load(f))


def _act(a_type, mag=1.0):
    return (a_type, np.array([mag], dtype=np.float32))


def _run(env, a_type, steps=30, mag=1.0, only=None):
    """Run the whole env with every agent playing a_type; return the env."""
    env.reset(seed=1)
    for _ in range(steps):
        if not env.agents:
            break
        env.step({a: _act(a_type, mag) for a in env.agents if only is None or a == only})
    return env


# ── backward compatibility ────────────────────────────────────────────────────

def test_zero_shock_matches_legacy_dynamics(personas):
    legacy = _run(make_ecosim_env(personas, max_steps=30, seed=1), ACTION_SAVE)
    econ = _run(make_ecosim_env(personas, max_steps=30, seed=1, shock=Shock()), ACTION_SAVE)
    for aid in legacy._budget:
        assert econ._budget[aid]["liquidity"] == pytest.approx(legacy._budget[aid]["liquidity"])
        assert econ._budget[aid]["debt_to_income"] == pytest.approx(legacy._budget[aid]["debt_to_income"])


def test_observation_includes_perceived_shock(personas):
    shock = PRESETS["severe"]
    env = make_ecosim_env(personas, max_steps=5, seed=0, shock=shock)
    obs, _ = env.reset(seed=0)
    o = obs[env.possible_agents[0]]
    assert o.shape == (OBS_DIM,)
    np.testing.assert_allclose(o[-3:], [shock.essential_cost, shock.income, shock.credit_tightness],
                               rtol=1e-5)
    # shock-free envs see zeros there
    env0 = make_ecosim_env(personas, max_steps=5, seed=0)
    obs0, _ = env0.reset(seed=0)
    np.testing.assert_allclose(obs0[env0.possible_agents[0]][-3:], [0, 0, 0])


# ── the shock reaches budgets ────────────────────────────────────────────────

def test_shock_drains_liquidity_more_for_low_literacy_persona(personas):
    calm = _run(make_ecosim_env(personas, max_steps=30, seed=1, shock=Shock()), ACTION_SAVE, mag=0.0)
    hit = _run(make_ecosim_env(personas, max_steps=30, seed=1, shock=PRESETS["severe"]),
               ACTION_SAVE, mag=0.0)   # magnitude 0: isolate the shock from saving
    lost = {a: calm._budget[a]["liquidity"] - hit._budget[a]["liquidity"] for a in calm._budget}
    assert all(v > 0 for v in lost.values()), "the shock should cost every persona liquidity"
    # struggling_worker (literacy 0.2) has thinner margins than tech-savvy_investor (0.95)
    assert lost["struggling_worker"] > lost["tech-savvy_investor"]


def test_randomized_shock_changes_between_episodes(personas):
    env = make_ecosim_env(personas, max_steps=5, seed=7, randomize_shock=True)
    seen = set()
    for _ in range(12):
        env.reset()
        seen.add(tuple(round(v, 3) for v in env.current_shock.to_dict().values()))
    assert len(seen) > 3, "randomize_shock should sample different shocks"


# ── insolvency -> forced default ─────────────────────────────────────────────

def test_running_out_of_cash_forces_a_default(personas):
    env = make_ecosim_env(personas, max_steps=40, seed=1, shock=PRESETS["severe"])
    env.reset(seed=1)
    forced_tick = None
    out_of_cash_ticks = 0
    for tick in range(40):
        if "struggling_worker" not in env.agents:
            break
        # struggling_worker keeps spending; everyone else just saves
        acts = {a: _act(ACTION_SPEND if a == "struggling_worker" else ACTION_SAVE) for a in env.agents}
        _, _, terms, _, infos = env.step(acts)
        if infos["struggling_worker"]["liquidity"] <= 0.02:
            out_of_cash_ticks += 1
        if infos["struggling_worker"]["forced_default"]:
            forced_tick = tick
            assert terms["struggling_worker"] is True
            break
    assert forced_tick is not None, "an agent that keeps spending under a severe shock must go insolvent"
    assert out_of_cash_ticks >= INSOLVENCY_TICKS
    assert "struggling_worker" not in env.agents


def test_no_forced_default_without_economy_mode(personas):
    env = make_ecosim_env(personas, max_steps=30, seed=1)          # legacy: no shock arg
    _run(env, ACTION_SPEND)                                        # everyone spends to zero
    assert not env._forced_default
    assert len(env.agents) == 0 or all(a not in env._agents_done for a in env.agents)


# ── reward makes personas differ ─────────────────────────────────────────────

def _one_step_reward(personas, aid, a_type):
    env = make_ecosim_env(personas, max_steps=5, seed=3, shock=Shock())
    env.reset(seed=3)
    acts = {a: _act(ACTION_SAVE, 0.0) for a in env.agents}
    acts[aid] = _act(a_type, 1.0)
    _, rewards, _, _, _ = env.step(acts)
    return rewards[aid]


def test_spending_pays_for_a_high_spending_bias_persona(personas):
    # aggressive_student: spending_bias 0.8, risk_appetite 0.9 -> spending is worth it
    assert _one_step_reward(personas, "aggressive_student", ACTION_SPEND) > \
           _one_step_reward(personas, "aggressive_student", ACTION_SAVE)


def test_defaulting_is_penalised(personas):
    for aid in ("aggressive_student", "conservative_saver"):
        assert _one_step_reward(personas, aid, ACTION_DEFAULT) < \
               _one_step_reward(personas, aid, ACTION_SAVE)


# ── shock arithmetic ─────────────────────────────────────────────────────────

def test_shock_from_deltas_sums_and_clamps():
    nodes = [{"deltas": {"discretionary_spend_pct": -0.2, "savings_rate_pct": 0.1,
                         "essential_cost_index_pct": 0.1, "credit_availability_pct": -0.15}}] * 2
    s = shock_from_deltas(nodes)
    assert s.essential_cost == pytest.approx(0.2)
    assert s.demand == pytest.approx(-0.4)
    assert s.income == pytest.approx(-0.2)             # half of the demand shock
    assert s.credit_tightness == pytest.approx(0.3)    # tighter credit = positive
    assert s.savings == pytest.approx(0.2)

    huge = shock_from_deltas([{"deltas": {"essential_cost_index_pct": 1.0}}] * 10)
    assert huge.essential_cost == MAX_SHOCK            # clamped


def test_nodes_without_deltas_are_zero_shock():
    assert shock_from_deltas([{"node_id": 1}, {"node_id": 2}]).is_zero
    assert shock_from_deltas([]).is_zero


def test_macro_from_shock_baseline_and_direction():
    assert macro_from_shock(Shock()) == {"inflation_rate": BASE_INFLATION,
                                         "repo_rate": BASE_REPO, "fuel_price_index": BASE_FUEL}
    m = macro_from_shock(Shock(essential_cost=0.3, credit_tightness=0.3))
    assert m["inflation_rate"] > BASE_INFLATION and m["repo_rate"] > BASE_REPO


def test_sample_random_shock_in_range():
    rng = np.random.default_rng(0)
    for _ in range(200):
        s = sample_random_shock(rng)
        assert -MAX_SHOCK <= s.essential_cost <= MAX_SHOCK
        assert -MAX_SHOCK <= s.demand <= MAX_SHOCK
