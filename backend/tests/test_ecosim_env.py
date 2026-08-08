"""
Module 4 validation test — proves the EcoSimEnv interaction loop works
end to end with a random policy, per docs/ARCHITECTURE.md section 7.1-7.2.
"""

import json
import os

from simulation.env_factory import personas_from_fixtures
from simulation.ecosim_env import make_ecosim_env
from simulation.random_policy import run_random_episode

FIXTURES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "personas.json"
)


def test_random_episode_runs_and_mutates_macro_state():
    with open(FIXTURES_PATH) as f:
        fixture_data = json.load(f)

    personas = personas_from_fixtures(fixture_data)
    assert len(personas) == 10

    env = make_ecosim_env(personas=personas, max_steps=20, seed=42)

    result = run_random_episode(env, n_ticks=20, seed=42)

    # 1. The episode actually ran
    assert result["tick_count"] > 0

    # 2. Active agent counts stayed within valid bounds every tick
    for count in result["per_tick_agent_counts"]:
        assert 0 <= count <= 10

    # 3. Macro state actually changed — proves the loop isn't a no-op
    macro_initial = result["macro_initial"]
    macro_final = result["macro_final"]
    assert macro_initial != macro_final, (
        f"Macro state did not change over the episode: "
        f"initial={macro_initial}, final={macro_final}"
    )
