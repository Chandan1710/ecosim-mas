"""
Module 5 test — proves the RLlib PPO training pipeline runs end-to-end,
produces a checkpoint, and contains all 10 persona policies.

Strategy
--------
- Calls run_training() directly (not a subprocess) so pytest captures output
  and errors cleanly.
- Uses num_iterations=1 to keep the test fast (a few seconds, not minutes).
- Checkpoint dir is scoped to a temp directory to avoid polluting the repo.
- After training, reads the checkpoint's rllib_checkpoint.json to verify all
  10 policy IDs are present — this confirms RLlib saved weights for each
  archetype, not just one shared policy.

No live DB, no API keys required.
"""

import json
import os
import tempfile

import pytest

# These imports may raise ImportError if Ray is not installed.
# The test is marked xfail with reason so it appears in CI reports without
# blocking the suite when ray is absent.
try:
    import ray  # noqa: F401
    _ray_available = True
except ImportError:
    _ray_available = False

pytestmark = pytest.mark.skipif(
    not _ray_available,
    reason="ray[rllib] not installed — skipping RLlib training test"
)

# ── expected policy IDs (must match train.py POLICY_IDS) ─────────────────

EXPECTED_POLICY_IDS = {
    "frugal_senior",
    "aggressive_student",
    "cautious_professional",
    "impulse_spender",
    "optimistic_entrepreneur",
    "struggling_worker",
    "balanced_family",
    "wealthy_retiree",
    "tech-savvy_investor",
    "conservative_saver",
}


def test_rllib_training_pipeline():
    """
    Full pipeline test:
    1. Runs 1 PPO iteration (minimal, proves no crash).
    2. Checkpoint directory is created.
    3. All 10 policy IDs are in the checkpoint metadata.
    """
    from simulation.train import run_training

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = run_training(
            num_iterations=1,
            checkpoint_dir=tmpdir,
            seed=0,
        )

        # ── assertion 1: training completed and returned a path ─────────────
        assert checkpoint_path, "run_training() returned empty checkpoint path"

        # ── assertion 2: checkpoint directory actually exists ────────────────
        assert os.path.isdir(checkpoint_path), (
            f"Checkpoint path does not exist or is not a directory: {checkpoint_path}"
        )

        # ── assertion 3: all 10 policies are in the checkpoint ───────────────
        #
        # RLlib 2.51+ (new API stack) stores each policy's RL module weights at:
        #   <checkpoint>/learner_group/learner/rl_module/<policy_id>/
        # Older API stack stored them under:
        #   <checkpoint>/policies/<policy_id>/
        # Even older versions put policy_ids in rllib_checkpoint.json.
        # We try all three, in order.

        policy_ids_in_checkpoint: set = set()

        # ① New API stack (Ray 2.40+): learner_group/learner/rl_module/<pid>/
        rl_module_dir = os.path.join(
            checkpoint_path, "learner_group", "learner", "rl_module"
        )
        if os.path.isdir(rl_module_dir):
            policy_ids_in_checkpoint = {
                d for d in os.listdir(rl_module_dir)
                if os.path.isdir(os.path.join(rl_module_dir, d))
            }

        # ② Old API stack: checkpoint/policies/<pid>/
        if not policy_ids_in_checkpoint:
            policies_dir = os.path.join(checkpoint_path, "policies")
            if os.path.isdir(policies_dir):
                policy_ids_in_checkpoint = {
                    d for d in os.listdir(policies_dir)
                    if os.path.isdir(os.path.join(policies_dir, d))
                }

        # ③ JSON metadata fallback
        if not policy_ids_in_checkpoint:
            for root, _, files in os.walk(checkpoint_path):
                for fname in files:
                    if fname == "rllib_checkpoint.json":
                        meta = json.load(open(os.path.join(root, fname)))
                        policy_ids_in_checkpoint = set(
                            meta.get("policy_ids") or meta.get("module_ids") or []
                        )
                        if policy_ids_in_checkpoint:
                            break
                if policy_ids_in_checkpoint:
                    break

        assert policy_ids_in_checkpoint, (
            f"Could not find any policy IDs in checkpoint at {checkpoint_path}. "
            f"Directory tree: {list(os.walk(checkpoint_path))}"
        )
        assert EXPECTED_POLICY_IDS == policy_ids_in_checkpoint, (
            f"Policy ID mismatch.\n"
            f"  Expected : {sorted(EXPECTED_POLICY_IDS)}\n"
            f"  Got      : {sorted(policy_ids_in_checkpoint)}"
        )
