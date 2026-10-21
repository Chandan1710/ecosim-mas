"""
Tests for simulation/policy_runtime.py — live inference with a safe fallback.

What these prove
----------------
* With no checkpoint (or a broken one) the runner NEVER raises; it falls back to
  random sampling and says why. The live stream must keep working.
* ECOSIM_POLICY=random forces random mode.
* find_latest_checkpoint picks the newest checkpoint folder.
* A real (1-iteration) RLlib checkpoint loads, produces actions in the exact
  (action_type:int, magnitude:ndarray[1]) shape EcoSimEnv.step() accepts, and a
  full episode runs. (This one trains for a few seconds, like
  test_rllib_training.py, and is skipped if ray/torch are not installed.)
* One persona's inference failing degrades only that agent to random.
"""

import json
import os
import time

import numpy as np
import pytest

from simulation.ecosim_env import make_ecosim_env
from simulation.env_factory import personas_from_fixtures
from simulation.policy_runtime import (
    MODE_RANDOM,
    MODE_RLLIB,
    PolicyRunner,
    find_latest_checkpoint,
)

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "personas.json")

try:
    import ray  # noqa: F401
    import torch  # noqa: F401
    _have_rllib = True
except Exception:
    _have_rllib = False

needs_rllib = pytest.mark.skipif(not _have_rllib, reason="ray[rllib] + torch not installed")


@pytest.fixture
def env_and_obs():
    with open(_FIXTURES) as f:
        personas = personas_from_fixtures(json.load(f))
    env = make_ecosim_env(personas, max_steps=30, seed=0)
    obs, _ = env.reset(seed=0)
    return env, obs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # test_simulation_run.py pins ECOSIM_POLICY=random for its own tests; these
    # tests must control that variable themselves.
    monkeypatch.delenv("ECOSIM_POLICY", raising=False)
    monkeypatch.delenv("ECOSIM_CHECKPOINT", raising=False)
    monkeypatch.delenv("ECOSIM_POLICY_DETERMINISTIC", raising=False)


def _assert_valid_actions(env, actions):
    assert set(actions) == set(env.agents)
    for a_type, a_mag in actions.values():
        assert int(a_type) in (0, 1, 2)
        a_mag = np.asarray(a_mag)
        assert a_mag.shape == (1,)
        assert 0.0 <= float(a_mag[0]) <= 1.0


def _fake_checkpoint(root, name):
    d = os.path.join(root, name, "learner_group", "learner", "rl_module", "frugal_senior")
    os.makedirs(d)
    return os.path.join(root, name)


def test_no_checkpoint_falls_back_to_random(tmp_path, env_and_obs):
    env, obs = env_and_obs
    runner = PolicyRunner.load(str(tmp_path))          # empty folder
    assert runner.mode == MODE_RANDOM
    assert "no checkpoint" in runner.reason
    _assert_valid_actions(env, runner.select_actions(env, obs))


def test_env_var_forces_random(monkeypatch, tmp_path):
    _fake_checkpoint(str(tmp_path), "run_1")
    monkeypatch.setenv("ECOSIM_POLICY", "random")
    runner = PolicyRunner.load(str(tmp_path))
    assert runner.mode == MODE_RANDOM
    assert "ECOSIM_POLICY" in runner.reason


def test_find_latest_checkpoint_picks_newest(tmp_path):
    assert find_latest_checkpoint(str(tmp_path)) is None
    old = _fake_checkpoint(str(tmp_path), "run_old")
    new = _fake_checkpoint(str(tmp_path), "run_new")
    os.utime(old, (time.time() - 1000, time.time() - 1000))
    os.utime(new, (time.time(), time.time()))
    assert find_latest_checkpoint(str(tmp_path)) == new
    # a checkpoint directory passed directly is returned as-is
    assert find_latest_checkpoint(new) == new
    assert find_latest_checkpoint(str(tmp_path / "does_not_exist")) is None


@needs_rllib
def test_corrupt_checkpoint_falls_back_to_random(tmp_path, env_and_obs):
    env, obs = env_and_obs
    ckpt = _fake_checkpoint(str(tmp_path), "run_broken")   # empty module dir
    runner = PolicyRunner.load(ckpt)
    assert runner.mode == MODE_RANDOM
    assert "failed to load" in runner.reason
    _assert_valid_actions(env, runner.select_actions(env, obs))


def test_one_persona_failing_degrades_only_that_agent(env_and_obs):
    env, obs = env_and_obs
    # A module that cannot run -> _act_one raises -> that agent samples randomly.
    runner = PolicyRunner(modules={"frugal_senior": object()}, checkpoint="fake")
    assert runner.mode == MODE_RLLIB
    _assert_valid_actions(env, runner.select_actions(env, obs))


@needs_rllib
def test_real_checkpoint_loads_and_runs_an_episode(tmp_path):
    from simulation.train import run_training

    ckpt = run_training(num_iterations=1, checkpoint_dir=str(tmp_path / "ckpt"), seed=0)
    runner = PolicyRunner.load(ckpt)
    assert runner.mode == MODE_RLLIB, runner.reason
    assert len(runner._modules) == 10

    with open(_FIXTURES) as f:
        personas = personas_from_fixtures(json.load(f))
    env = make_ecosim_env(personas, max_steps=30, seed=3)
    obs, _ = env.reset(seed=3)
    steps = 0
    while env.agents:
        actions = runner.select_actions(env, obs)
        _assert_valid_actions(env, actions)
        obs, *_ = env.step(actions)
        steps += 1
    assert 1 <= steps <= 30
