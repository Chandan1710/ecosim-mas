"""
evaluate_policy.py — does the trained checkpoint actually behave differently
from random? Run this after training, before trusting the live demo.

Usage (from backend/, venv active):
  python -m simulation.evaluate_policy
  python -m simulation.evaluate_policy --checkpoint simulation/checkpoints/run_20261021_231500
  python -m simulation.evaluate_policy --episodes 50 --max-steps 30

It plays the same seeded episodes with (a) random actions and (b) the trained
per-persona policies, then prints, per persona and overall:
  - survival : % of episodes the agent did NOT default
  - end liq. : mean liquidity at the end of the episode
  - return   : mean total reward
  - mix      : action mix  Spend / Save / Default  (%)

If "trained" looks the same as "random", the checkpoint is under-trained (or
the reward gives the policy nothing to learn) — see simulation/train.py.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from typing import Dict, List

import numpy as np

from simulation.ecosim_env import make_ecosim_env, ACTION_SPEND, ACTION_SAVE, ACTION_DEFAULT
from simulation.env_factory import personas_from_fixtures
from simulation.policy_runtime import PolicyRunner, find_latest_checkpoint, MODE_RLLIB

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "personas.json")


def _run_episode(runner: PolicyRunner, personas, seed: int, max_steps: int) -> Dict[str, dict]:
    env = make_ecosim_env(personas, max_steps=max_steps, seed=seed)
    for aid in env.possible_agents:           # reproducible random baseline
        env.action_space(aid).seed(seed)
    obs, _ = env.reset(seed=seed)

    stats = {
        aid: {"ret": 0.0, "defaulted": False, "end_liq": None,
              "n": {ACTION_SPEND: 0, ACTION_SAVE: 0, ACTION_DEFAULT: 0}}
        for aid in env.possible_agents
    }
    while env.agents:
        actions = runner.select_actions(env, obs)
        obs, rewards, terms, truncs, infos = env.step(actions)
        for aid, (a_type, _mag) in actions.items():
            st = stats[aid]
            st["n"][int(a_type)] += 1
            st["ret"] += float(rewards.get(aid, 0.0))
            st["end_liq"] = infos.get(aid, {}).get("liquidity", st["end_liq"])
            if int(a_type) == ACTION_DEFAULT:
                st["defaulted"] = True
    return stats


def evaluate(runner: PolicyRunner, personas, episodes: int, max_steps: int, seed: int):
    agg: Dict[str, dict] = defaultdict(lambda: {"ret": [], "def": [], "liq": [],
                                                "n": np.zeros(3)})
    for ep in range(episodes):
        for aid, st in _run_episode(runner, personas, seed + ep, max_steps).items():
            a = agg[aid]
            a["ret"].append(st["ret"])
            a["def"].append(1.0 if st["defaulted"] else 0.0)
            a["liq"].append(st["end_liq"] if st["end_liq"] is not None else 0.0)
            a["n"] += np.array([st["n"][ACTION_SPEND], st["n"][ACTION_SAVE], st["n"][ACTION_DEFAULT]])
    return agg


def _fmt_row(name: str, a: dict) -> str:
    n = a["n"]
    tot = max(1.0, n.sum())
    mix = " / ".join(f"{100 * x / tot:3.0f}" for x in n)
    return (f"  {name:<24} {100 * (1 - np.mean(a['def'])):5.0f}%  {np.mean(a['liq']):7.2f}  "
            f"{np.mean(a['ret']):8.2f}   {mix}")


def _overall(agg: Dict[str, dict]) -> dict:
    return {
        "ret": [x for a in agg.values() for x in a["ret"]],
        "def": [x for a in agg.values() for x in a["def"]],
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare trained RLlib policies against random.")
    ap.add_argument("--checkpoint", default=None,
                    help="Checkpoint dir (or a folder of runs). Default: newest under simulation/checkpoints.")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(_FIXTURES) as f:
        personas = personas_from_fixtures(json.load(f))
    order = [p.agent_id for p in personas]

    ckpt = find_latest_checkpoint(args.checkpoint)
    print(f"Episodes: {args.episodes}  horizon: {args.max_steps}  seed: {args.seed}")
    print(f"Checkpoint: {ckpt or 'NONE FOUND'}")

    random_runner = PolicyRunner(reason="evaluation baseline")
    print_report("RANDOM policy", evaluate(random_runner, personas, args.episodes,
                                           args.max_steps, args.seed), order)

    if ckpt is None:
        print("\nNo checkpoint to evaluate. Train one first:\n"
              "  python -m simulation.train --iterations 150 --train-batch-size 2000 --max-steps 30")
        return
    trained = PolicyRunner.load(ckpt)
    if trained.mode != MODE_RLLIB:
        print(f"\nCould not load the checkpoint: {trained.reason}")
        return
    print_report("TRAINED policy", evaluate(trained, personas, args.episodes,
                                            args.max_steps, args.seed), order)


if __name__ == "__main__":
    main()
