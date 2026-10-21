"""
policy_runtime.py — live inference for the trained per-persona RLlib policies.

Why this module exists
----------------------
Module 5 (train.py) saves a Ray RLlib PPO checkpoint with one RLModule per
persona. Module 9 (simulate.py) used to sample *random* actions. This module
bridges the two: it loads each persona's RLModule from a checkpoint ONCE and
turns an observation into an (action_type, magnitude) action — the same shape
EcoSimEnv.step() expects — without needing a running Ray cluster.

Design rules
------------
* NEVER raise into the request path. If Ray/torch are missing, no checkpoint
  exists, or loading fails, we fall back to random sampling and record why
  (``PolicyRunner.reason``). The live demo must keep working.
* The random fallback still calls ``env.action_space(agent_id).sample()`` —
  exactly what simulate.py did before — so existing tests that patch the
  action space keep working unchanged.
* ``ECOSIM_POLICY=random`` forces random mode; ``ECOSIM_CHECKPOINT=<path>``
  pins a specific checkpoint (otherwise the newest one under
  ``simulation/checkpoints`` is used).
* ``ECOSIM_POLICY_DETERMINISTIC=1`` uses the policy's most likely action
  instead of sampling from it.

Checkpoint layout expected (Ray 2.40+ new API stack, matches the test in
tests/test_rllib_training.py):
    <checkpoint>/learner_group/learner/rl_module/<persona_slug>/
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_ROOT = os.path.join(os.path.dirname(__file__), "checkpoints")
_RL_MODULE_SUBPATH = os.path.join("learner_group", "learner", "rl_module")

MODE_RLLIB = "rllib"
MODE_RANDOM = "random"


def _is_checkpoint_dir(path: str) -> bool:
    return os.path.isdir(os.path.join(path, _RL_MODULE_SUBPATH))


def find_latest_checkpoint(root: Optional[str] = None) -> Optional[str]:
    """
    Return the newest checkpoint directory at or under ``root``.

    ``root`` may itself be a checkpoint, or a folder containing one or more
    checkpoint folders (e.g. ``checkpoints/run_20261021_231500``). Returns None
    if nothing usable is found.
    """
    root = root or DEFAULT_CHECKPOINT_ROOT
    if not os.path.isdir(root):
        return None
    if _is_checkpoint_dir(root):
        return root

    candidates = []
    for dirpath, dirnames, _ in os.walk(root):
        if _is_checkpoint_dir(dirpath):
            candidates.append(dirpath)
            dirnames[:] = []  # don't descend into a checkpoint
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


class PolicyRunner:
    """Selects actions for all active agents, via RLlib policies or random."""

    def __init__(
        self,
        modules: Optional[Dict[str, Any]] = None,
        checkpoint: Optional[str] = None,
        reason: str = "",
        deterministic: bool = False,
    ):
        self._modules = modules or {}
        self.checkpoint = checkpoint
        self.reason = reason
        self.deterministic = deterministic

    # ── public info ──────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return MODE_RLLIB if self._modules else MODE_RANDOM

    def describe(self) -> str:
        if self.mode == MODE_RLLIB:
            return (f"RLlib policies ({len(self._modules)} personas) from "
                    f"{self.checkpoint}")
        return f"random policy ({self.reason})"

    # ── loading ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, checkpoint: Optional[str] = None) -> "PolicyRunner":
        """Load policies from a checkpoint. Never raises; falls back to random."""
        if os.environ.get("ECOSIM_POLICY", "").strip().lower() == MODE_RANDOM:
            return cls(reason="ECOSIM_POLICY=random")

        deterministic = os.environ.get("ECOSIM_POLICY_DETERMINISTIC", "") in ("1", "true", "True")
        ckpt_arg = checkpoint or os.environ.get("ECOSIM_CHECKPOINT")
        ckpt = find_latest_checkpoint(ckpt_arg)
        if ckpt is None:
            where = ckpt_arg or DEFAULT_CHECKPOINT_ROOT
            return cls(reason=f"no checkpoint found under {where}")

        try:
            import torch  # noqa: F401
            from ray.rllib.core.rl_module.rl_module import RLModule
        except Exception as exc:  # ImportError, or ray/torch import-time failures
            return cls(reason=f"ray/torch not importable: {exc}")

        module_root = os.path.join(ckpt, _RL_MODULE_SUBPATH)
        modules: Dict[str, Any] = {}
        try:
            for pid in sorted(os.listdir(module_root)):
                pdir = os.path.join(module_root, pid)
                if os.path.isdir(pdir):
                    modules[pid] = RLModule.from_checkpoint(pdir)
        except Exception as exc:
            logger.exception("Failed loading RLModules from %s", ckpt)
            return cls(reason=f"failed to load {ckpt}: {exc}")

        if not modules:
            return cls(reason=f"no RLModules inside {module_root}")

        logger.info("Loaded %d RLlib policies from %s", len(modules), ckpt)
        return cls(modules=modules, checkpoint=ckpt, deterministic=deterministic)

    # ── inference ────────────────────────────────────────────────────────────

    def _act_one(self, agent_id: str, obs: np.ndarray):
        """Run one persona's RLModule on one observation -> (int, np.ndarray[1])."""
        import torch
        from ray.rllib.core.columns import Columns

        module = self._modules[agent_id]
        batch = {Columns.OBS: torch.from_numpy(np.asarray(obs, dtype=np.float32)).unsqueeze(0)}
        with torch.no_grad():
            out = module.forward_inference(batch)
            dist_cls = module.get_inference_action_dist_cls()
            dist = dist_cls.from_logits(out[Columns.ACTION_DIST_INPUTS])
            if self.deterministic:
                dist = dist.to_deterministic()
            action = dist.sample()

        a_type, a_mag = action[0], action[1]
        a_type = int(np.asarray(a_type.detach().cpu()).reshape(-1)[0])
        a_mag = np.asarray(a_mag.detach().cpu(), dtype=np.float32).reshape(-1)[:1]
        a_mag = np.clip(a_mag, 0.0, 1.0).astype(np.float32)
        return a_type, a_mag

    def select_actions(self, env, observations: Dict[str, np.ndarray]) -> Dict[str, tuple]:
        """
        Return {agent_id: (action_type, magnitude)} for every agent in env.agents.

        Per-agent fallback: if one persona has no module or its inference
        fails, that agent samples randomly instead of failing the whole tick.
        """
        actions: Dict[str, tuple] = {}
        for agent_id in env.agents:
            if self._modules and agent_id in self._modules and agent_id in observations:
                try:
                    actions[agent_id] = self._act_one(agent_id, observations[agent_id])
                    continue
                except Exception as exc:
                    logger.warning("Policy inference failed for %s (%s); sampling randomly",
                                   agent_id, exc)
            actions[agent_id] = env.action_space(agent_id).sample()
        return actions
