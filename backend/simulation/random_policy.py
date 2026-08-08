"""
Random policy runner for EcoSimEnv — module 4 validation harness.

Not a training loop. Just samples from each agent's action space uniformly
to prove the interaction loop works end-to-end before introducing RLlib.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
import numpy as np
from simulation.ecosim_env import EcoSimEnv, AgentPersona


def run_random_episode(
    env: EcoSimEnv,
    n_ticks: int = 20,
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """
    Run one episode with a random policy for all agents.

    Returns a summary dict with:
      - tick_count: how many ticks actually ran
      - macro_initial: macro state at tick 0
      - macro_final: macro state at the end
      - agent_final_budgets: per-agent final budget state
      - per_tick_agent_counts: list of active-agent counts per tick
    """
    observations, _ = env.reset(seed=seed)

    macro_initial = env._macro_snapshot()
    per_tick_counts: List[int] = []
    tick = 0

    while env.agents and tick < n_ticks:
        # Sample a random action for every currently-active agent
        actions = {
            agent_id: env.action_space(agent_id).sample()
            for agent_id in env.agents
        }

        observations, rewards, terminations, truncations, infos = env.step(actions)
        per_tick_counts.append(len(env.agents))
        tick += 1

    macro_final = env._macro_snapshot()
    agent_final_budgets = {
        aid: {
            "liquidity": env._budget[aid]["liquidity"],
            "debt_to_income": env._budget[aid]["debt_to_income"],
        }
        for aid in env.possible_agents
    }

    return {
        "tick_count": tick,
        "macro_initial": macro_initial,
        "macro_final": macro_final,
        "per_tick_agent_counts": per_tick_counts,
        "agent_final_budgets": agent_final_budgets,
    }
