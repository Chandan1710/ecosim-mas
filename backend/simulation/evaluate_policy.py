"""
evaluate_policy.py — does the trained checkpoint actually behave differently
from random, differ between personas, and respond to scenario shocks?
Run this after training, before trusting the live demo.

Usage (from backend/, venv active):
  python -m simulation.evaluate_policy
  python -m simulation.evaluate_policy --shock severe
  python -m simulation.evaluate_policy --checkpoint simulation/checkpoints/run_20261021_231500
  python -m simulation.evaluate_policy --episodes 50 --max-steps 30

It plays the same seeded episodes with (a) random actions and (b) the trained
per-persona policies, in the shock-driven economy (see simulation/shock.py):

  1. A per-persona table for ONE shock level (--shock none|mild|severe,
     default mild):
       survive : % of episodes the agent did NOT default (voluntarily or forced)
       end liq.: mean liquidity at the end of the episode
       return  : mean total reward
       mix     : action mix Spend / Save / Default (%)
  2. A shock sweep (none -> mild -> severe) for both policies, so you can see
     whether agents react to the shock: spending should fall and defaults
     should rise as the shock gets worse.
  3. How much personas differ: the min-max range of each persona's Spend %.
     A narrow range means every persona behaves the same.

If "trained" looks the same as "random", the checkpoint is under-trained.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

from simulation.ecosim_env import make_ecosim_env, ACTION_SPEND, ACTION_SAVE, ACTION_DEFAULT
from simulation.env_factory import personas_from_fixtures
from simulation.policy_runtime import PolicyRunner, find_latest_checkpoint, MODE_RLLIB
from simulation.shock import PRESETS, Shock, describe

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "personas.json")


def _run_episode(runner: PolicyRunner, personas, seed: int, max_steps: int,
                 shock: Optional[Shock] = None) -> Dict[str, dict]:
    env = make_ecosim_env(personas, max_steps=max_steps, seed=seed, shock=shock or Shock())
    for aid in env.possible_agents:           # reproducible random baseline
        env.action_space(aid).seed(seed)
    obs, _ = env.reset(seed=seed)

    stats = {
        aid: {"ret": 0.0, "defaulted": False, "forced": False, "end_liq": None,
              "n": {ACTION_SPEND: 0, ACTION_SAVE: 0, ACTION_DEFAULT: 0}}
        for aid in env.possible_agents
    }
    while env.agents:
        actions = runner.select_actions(env, obs)
        obs, rewards, terms, truncs, infos = env.step(actions)
        for aid, (a_type, _mag) in actions.items():
            st = stats[aid]
            a_type = int(a_type)
            if infos.get(aid, {}).get("forced_default"):
                a_type = ACTION_DEFAULT        # insolvency: shown/counted as a Default
                st["forced"] = True
            st["n"][a_type] += 1
            st["ret"] += float(rewards.get(aid, 0.0))
            st["end_liq"] = infos.get(aid, {}).get("liquidity", st["end_liq"])
            if a_type == ACTION_DEFAULT:
                st["defaulted"] = True
    return stats


def evaluate(runner: PolicyRunner, personas, episodes: int, max_steps: int, seed: int,
             shock: Optional[Shock] = None) -> Dict[str, dict]:
    agg: Dict[str, dict] = defaultdict(lambda: {"ret": [], "def": [], "forced": [],
                                                "liq": [], "n": np.zeros(3)})
    for ep in range(episodes):
        for aid, st in _run_episode(runner, personas, seed + ep, max_steps, shock).items():
            a = agg[aid]
            a["ret"].append(st["ret"])
            a["def"].append(1.0 if st["defaulted"] else 0.0)
            a["forced"].append(1.0 if st["forced"] else 0.0)
            a["liq"].append(st["end_liq"] if st["end_liq"] is not None else 0.0)
            a["n"] += np.array([st["n"][ACTION_SPEND], st["n"][ACTION_SAVE], st["n"][ACTION_DEFAULT]])
    return agg


def _mix(n) -> List[float]:
    tot = max(1.0, float(np.sum(n)))
    return [100.0 * float(x) / tot for x in n]


def _fmt_row(name: str, a: dict) -> str:
    mix = " / ".join(f"{x:3.0f}" for x in _mix(a["n"]))
    return (f"  {name:<24} {100 * (1 - np.mean(a['def'])):5.0f}%  {np.mean(a['liq']):7.2f}  "
            f"{np.mean(a['ret']):8.2f}   {mix}")


def _overall(agg: Dict[str, dict]) -> dict:
    return {
        "ret": [x for a in agg.values() for x in a["ret"]],
        "def": [x for a in agg.values() for x in a["def"]],
        "forced": [x for a in agg.values() for x in a["forced"]],
        "liq": [x for a in agg.values() for x in a["liq"]],
        "n": sum((a["n"] for a in agg.values()), np.zeros(3)),
    }


def print_report(title: str, agg: Dict[str, dict], order: List[str]) -> None:
    print(f"\n{title}")
    print(f"  {'persona':<24} {'survive':>6}  {'end liq':>7}  {'return':>8}   Spend/Save/Default %")
    for aid in order:
        print(_fmt_row(aid, agg[aid]))
    print("  " + "-" * 74)
    print(_fmt_row("ALL", _overall(agg)))


def print_sweep(results: Dict[str, Dict[str, Dict[str, dict]]], order: List[str]) -> None:
    """results[policy_name][shock_name] -> agg"""
    print("\nSHOCK SWEEP — does behaviour respond to the shock?")
    print(f"  {'policy':<8} {'shock':<8} {'survive':>7} {'forced':>7}  {'Spend/Save/Default %':<22} "
          f"{'persona Spend% range':<22}")
    for pol, by_shock in results.items():
        for shock_name, agg in by_shock.items():
            ov = _overall(agg)
            mix = " / ".join(f"{x:3.0f}" for x in _mix(ov["n"]))
            per_persona_spend = [_mix(agg[aid]["n"])[0] for aid in order]
            rng = f"{min(per_persona_spend):3.0f} - {max(per_persona_spend):3.0f}"
            print(f"  {pol:<8} {shock_name:<8} {100 * (1 - np.mean(ov['def'])):6.0f}% "
                  f"{100 * np.mean(ov['forced']):6.0f}%  {mix:<22} {rng:<22}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare trained RLlib policies against random.")
    ap.add_argument("--checkpoint", default=None,
                    help="Checkpoint dir (or a folder of runs). Default: newest under simulation/checkpoints.")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--shock", choices=list(PRESETS), default="mild",
                    help="Shock level for the per-persona tables (default: mild).")
    args = ap.parse_args()

    with open(_FIXTURES) as f:
        personas = personas_from_fixtures(json.load(f))
    order = [p.agent_id for p in personas]

    ckpt = find_latest_checkpoint(args.checkpoint)
    print(f"Episodes: {args.episodes}  horizon: {args.max_steps}  seed: {args.seed}")
    print(f"Checkpoint: {ckpt or 'NONE FOUND'}")
    print(f"Per-persona shock level '{args.shock}': {describe(PRESETS[args.shock])}")

    runners: Dict[str, PolicyRunner] = {"random": PolicyRunner(reason="evaluation baseline")}
    if ckpt is not None:
        trained = PolicyRunner.load(ckpt)
        if trained.mode == MODE_RLLIB:
            runners["trained"] = trained
        else:
            print(f"\nCould not load the checkpoint: {trained.reason}")
    else:
        print("\nNo checkpoint to evaluate. Train one first:\n"
              "  python -m simulation.train --iterations 30 --train-batch-size 2000 --max-steps 30")

    results: Dict[str, Dict[str, Dict[str, dict]]] = {}
    for name, runner in runners.items():
        results[name] = {}
        for shock_name, shock in PRESETS.items():
            results[name][shock_name] = evaluate(runner, personas, args.episodes,
                                                 args.max_steps, args.seed, shock)
        print_report(f"{name.upper()} policy — shock '{args.shock}'",
                     results[name][args.shock], order)

    print_sweep(results, order)


if __name__ == "__main__":
    main()
