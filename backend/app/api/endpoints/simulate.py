"""
Module 9: Live Simulation Streaming

POST /scenarios/{scenario_id}/simulate/start
    — Registers a prepared EcoSimEnv under a run_id and returns the ID
      immediately. The HTTP response does NOT block on simulation.

GET  /ws/simulate/{run_id}
    — WebSocket that drives the simulation step-by-step, streaming one
      JSON message per tick until the episode ends or the client disconnects.

Architecture note
-----------------
The simulation steps are driven *inside* the WebSocket handler using an
async for-loop with a small `asyncio.sleep` yield between ticks. This keeps
the design simple and works correctly with both the production ASGI server
(uvicorn) and Starlette's TestClient (which runs the ASGI app in a real
event loop). A background-task / queue approach was considered but requires
a real concurrent async runtime to schedule both producer and consumer;
the inline WebSocket driver is equivalent in practice for this single-node
deployment and is far more transparent.

Policy selection (simulation/policy_runtime.py):
  Actions come from the trained per-persona RLlib policies (module 5) when a
  checkpoint exists under simulation/checkpoints (or ECOSIM_CHECKPOINT). If
  there is no checkpoint, Ray/torch can't be imported, or ECOSIM_POLICY=random
  is set, the stream falls back to uniform-random sampling. Every tick message
  carries "policy": "rllib" | "random" so the client can tell which is live.

Known scope limits (deliberate, documented):
  1. A freshly trained-for-a-few-iterations checkpoint behaves close to random;
     meaningful behaviour needs a longer training run (see simulation/train.py).
  2. IN-MEMORY RUN REGISTRY: Active envs are tracked in a plain dict.
     This works for a single-process server but will not survive a restart
     or scale across multiple workers. Redis pub/sub is the right
     replacement and is explicitly deferred.
"""

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from db.session import SessionLocal
from models.scenarios import Scenario
from models.causal_chains import CausalChain
from simulation.env_factory import personas_from_db
from simulation.ecosim_env import EcoSimEnv
from app.services.memory import store_episode
from ml.predict import predict_risk_score
from simulation.policy_runtime import PolicyRunner
from simulation.shock import Shock, macro_from_shock, shock_from_deltas, describe as describe_shock
from app.services.llm import map_node_to_deltas

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory run registry (scope limit: single-process only) ─────────────────
# Maps run_id → dict containing {"env": EcoSimEnv, "base_essential_pressure": float}
ACTIVE_RUNS: Dict[str, dict] = {}

_TICK_DELAY_SECONDS = 1.2   # yield between ticks so the event loop stays responsive

# ── Policy runner (loaded once, lazily; see simulation/policy_runtime.py) ─────
_POLICY_RUNNER: Optional[PolicyRunner] = None


def get_policy_runner() -> PolicyRunner:
    """Return the process-wide PolicyRunner, loading it on first use."""
    global _POLICY_RUNNER
    if _POLICY_RUNNER is None:
        _POLICY_RUNNER = PolicyRunner.load()
        logger.info("Simulation policy: %s", _POLICY_RUNNER.describe())
    return _POLICY_RUNNER


# ── Request / Response models ─────────────────────────────────────────────────

class SimulateStartResponse(BaseModel):
    run_id: str
    scenario_id: int
    message: str
    shock: Optional[dict] = None   # the numeric shock this run applies to every agent


# ── Helpers: scenario -> mapped deltas -> Shock ───────────────────────────────

def _build_initial_macro(mapped_nodes: list) -> Dict[str, float]:
    """Starting macro state implied by the chain's mapped deltas (see simulation/shock.py)."""
    return macro_from_shock(shock_from_deltas(mapped_nodes))


def _get_essential_pressure_from_deltas(mapped_nodes: list) -> float:
    """Baseline essential_pressure [0,1] implied by the chain's essential-cost deltas."""
    return max(0.0, min(1.0, 0.5 + shock_from_deltas(mapped_nodes).essential_cost))


def _essential_pressure(shock: Shock, financial_literacy: float, liquidity: float) -> float:
    """
    Per-agent essential_pressure [0,1] (§9.3): how squeezed this agent is by the
    cost of essentials right now. Rises with the scenario's essential-cost shock
    (more for low-literacy personas, who have thinner margins — same exposure
    weight the environment uses) and as the agent's own liquidity runs low.
    Zero shock + healthy liquidity -> ~0.25, well below the 0.7 Grocery trigger.
    """
    exposure = 0.6 + 0.8 * (1.0 - financial_literacy)
    pressure = (0.25
                + 0.9 * max(0.0, shock.essential_cost) * exposure
                + 0.35 * max(0.0, 0.6 - liquidity))
    return max(0.0, min(1.0, pressure))


def _ensure_mapped_chain(chain_id: int) -> List[dict]:
    """
    Return the chain's nodes with numeric deltas attached, mapping any node that
    lacks them (module 6: Groq -> Ollama -> mock) and SAVING the result back to the
    causal_chains row, so a scenario always yields the same shock on later runs.

    Previously simulate/start read `node["deltas"]` from a stored chain that never
    had any (the mapper endpoint returned deltas without persisting them), so every
    scenario silently started from the neutral baseline.
    """
    db = SessionLocal()
    try:
        record = db.query(CausalChain).filter(CausalChain.id == chain_id).first()
        nodes = [dict(n) for n in (record.chain or [])]
        missing = [n for n in nodes if "deltas" not in n]
        if not missing:
            return nodes

        def _map(node: dict):
            try:
                return node["node_id"], map_node_to_deltas(node=node)["deltas"]
            except Exception as exc:
                logger.warning("Mapping node %s failed (%s); treating as no shock", node.get("node_id"), exc)
                return node["node_id"], None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = dict(pool.map(_map, missing))

        mapped_any = False
        for node in nodes:
            deltas = results.get(node["node_id"])
            if deltas is not None:
                node["deltas"] = deltas
                mapped_any = True
        if mapped_any:
            record.chain = nodes          # reassign so SQLAlchemy sees the JSON change
            db.commit()
        return nodes
    finally:
        db.close()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/scenarios/{scenario_id}/simulate/start",
    response_model=SimulateStartResponse,
    tags=["simulation"],
)
async def start_simulation(scenario_id: int):
    """
    Prepare a simulation run for the given scenario and return a run_id.

    Prerequisites:
      - The scenario must exist (module 1).
      - It must have a persisted causal chain (module 3).

    The causal chain nodes are used to seed the initial macro state.
    Personas are loaded from the PostgreSQL personas table.

    Connect to GET /ws/simulate/{run_id} to begin streaming tick results.

    Agent actions come from the trained RLlib policies when a checkpoint is
    available, otherwise a random policy — see the module docstring.
    """
    db = SessionLocal()
    try:
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not scenario:
            raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")

        chain_record = (
            db.query(CausalChain)
            .filter(CausalChain.scenario_id == scenario_id)
            .order_by(CausalChain.id.desc())
            .first()
        )
        if not chain_record:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No causal chain found for scenario {scenario_id}. "
                    "Call POST /scenarios/{id}/causal-chain first."
                ),
            )
    finally:
        db.close()

    # Map the chain to numeric deltas (and persist them), then collapse to one Shock
    # that the environment applies to every agent's budget each tick.
    mapped_nodes = await asyncio.to_thread(_ensure_mapped_chain, chain_record.id)
    shock = shock_from_deltas(mapped_nodes)
    initial_macro = macro_from_shock(shock)
    logger.info("Scenario %d: shock = %s | initial_macro = %s",
                scenario_id, describe_shock(shock), initial_macro)

    # Load personas from DB
    try:
        personas = personas_from_db()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not load personas from DB: {exc}. "
                "Seed the personas table via scripts/seed_db.py first."
            ),
        )

    env = EcoSimEnv(personas=personas, initial_macro=initial_macro, max_steps=30, shock=shock)
    base_essential_pressure = max(0.0, min(1.0, 0.5 + shock.essential_cost))

    # Loading RLlib/torch can take seconds the first time — keep it off the loop.
    runner = await asyncio.to_thread(get_policy_runner)

    run_id = str(uuid.uuid4())
    ACTIVE_RUNS[run_id] = {
        "env": env,
        "base_essential_pressure": base_essential_pressure,
        "runner": runner,
        "shock": shock,
    }

    return SimulateStartResponse(
        run_id=run_id,
        scenario_id=scenario_id,
        shock=shock.to_dict(),
        message=(
            "Simulation prepared. Connect to /ws/simulate/{run_id} to stream results. "
            f"Shock: {describe_shock(shock)}. Policy: {runner.describe()}"
        ),
    )


@router.websocket("/ws/simulate/{run_id}")
async def simulate_ws(websocket: WebSocket, run_id: str):
    """
    Drive and stream the simulation tick-by-tick over a WebSocket.

    Each message is a JSON object with:
      tick          — tick index (0-based)
      agent_actions — {agent_id: {action_type, magnitude, reward}}
      macro_state   — {inflation_rate, repo_rate, fuel_price_index}
      risk_score    — float [0,1] from the LightGBM predictor (module 8),
                      or null if the predictor is unavailable
      active_agents — number of agents still in the episode

    A final {"status": "simulation_complete"} message is sent when the
    episode ends, then the WebSocket closes cleanly.

    Policy: trained RLlib policies or random fallback — "policy" field says which.
    Memory: each agent's (event, action, outcome) is persisted to Qdrant
            (module 7) after every tick.
    """
    if run_id not in ACTIVE_RUNS:
        await websocket.close(code=4404, reason=f"Run {run_id} not found")
        return

    run_state = ACTIVE_RUNS.pop(run_id)   # take ownership; allows GC after run
    env = run_state["env"]
    base_essential_pressure = run_state["base_essential_pressure"]
    runner = run_state.get("runner") or get_policy_runner()
    shock = run_state.get("shock") or Shock()

    await websocket.accept()

    # Initialize post-processing state per agent (needs state, zones)
    agent_states = {}
    for aid in env.possible_agents:
        persona = env._personas.get(aid)
        fin_lit = persona.financial_literacy if persona else 0.5
        bias = persona.spending_bias if persona else 0.5
        agent_states[aid] = {
            "budget_anxiety": 0.5,
            "essential_pressure": _essential_pressure(shock, fin_lit, 1.0),
            "discretionary_appetite": 0.5 * bias,
            "zone": "Home",
            "zone_history": [],
            "financial_literacy": fin_lit,
            "spending_bias": bias,
        }

    try:
        observations, _ = env.reset()

        for tick in range(env.max_steps):
            if not env.agents:
                break

            # ── 1. Select actions (trained RLlib policies, or random fallback) ──
            actions = runner.select_actions(env, observations)

            # ── 2. Step the environment ──────────────────────────────────────
            observations, rewards, terminations, truncations, infos = env.step(actions)

            # An agent forced into default by insolvency (ran out of cash) is shown as
            # a Default so the client freezes it and peers perceive it as one.
            for aid in list(actions):
                if infos.get(aid, {}).get("forced_default"):
                    actions[aid] = (2, actions[aid][1])

            # ── 2a. Needs State Update (Post-processing layer, §9.3) ─────────
            for aid, action in actions.items():
                state = agent_states[aid]
                a_type, a_mag = action
                mag = float(a_mag[0])
                
                # Update budget_anxiety based on action and current liquidity
                liquidity = infos.get(aid, {}).get("liquidity", 1.0)
                state["essential_pressure"] = _essential_pressure(
                    shock, state["financial_literacy"], liquidity)
                if mag > 0.3 and liquidity < 0.3:
                    state["budget_anxiety"] = min(1.0, state["budget_anxiety"] + 0.1)
                else:
                    state["budget_anxiety"] = max(0.0, state["budget_anxiety"] - 0.02)
                
                # Update discretionary_appetite (inverse of anxiety, modulated by bias)
                state["discretionary_appetite"] = max(0.0, min(1.0, (1.0 - state["budget_anxiety"]) * state["spending_bias"]))

            # ── 2b. Zone Assignment (§9.3) ───────────────────────────────────
            for aid in actions.keys():
                state = agent_states[aid]
                
                if state["essential_pressure"] > 0.7:
                    new_zone = "Grocery"
                elif state["budget_anxiety"] > 0.7:
                    new_zone = "Home"
                elif state["discretionary_appetite"] > 0.6 and state["budget_anxiety"] < 0.4:
                    candidates = ["Mall", "Café", "Theater"]
                    recent = state["zone_history"][-3:]
                    available = [c for c in candidates if c not in recent]
                    new_zone = available[0] if available else candidates[0]
                else:
                    new_zone = "Workplace" if tick % 2 == 0 else "Home"
                
                state["zone"] = new_zone
                state["zone_history"].append(new_zone)
                if len(state["zone_history"]) > 5:
                    state["zone_history"].pop(0)

            # ── 2c. Co-location & Peer Influence Nudge (§7.5) ────────────────
            zone_to_agents = {}
            for aid in actions.keys():
                z = agent_states[aid]["zone"]
                zone_to_agents.setdefault(z, []).append(aid)
            
            co_located_pairs = []
            for z, agents_in_zone in zone_to_agents.items():
                if len(agents_in_zone) < 2:
                    continue
                # For simplicity, pairwise influence for all unique pairs in zone
                for i in range(len(agents_in_zone)):
                    for j in range(i + 1, len(agents_in_zone)):
                        a1, a2 = agents_in_zone[i], agents_in_zone[j]
                        s1, s2 = agent_states[a1], agent_states[a2]
                        act1 = int(actions[a1][0])
                        act2 = int(actions[a2][0])
                        
                        # a1 influences a2
                        nudge_1_on_2 = 0.0
                        if act1 == 2: # Default raises anxiety
                            s2["budget_anxiety"] += 0.05 * (1.0 - s2["financial_literacy"])
                            nudge_1_on_2 = 0.05
                        elif act1 == 0 and z in ["Mall", "Café", "Theater"]: # Discretionary spend raises appetite
                            s2["discretionary_appetite"] += 0.05 * (1.0 - s2["financial_literacy"])
                            nudge_1_on_2 = 0.05
                        elif act1 == 1: # Save lowers anxiety
                            s2["budget_anxiety"] -= 0.05 * (1.0 - s2["financial_literacy"])
                            nudge_1_on_2 = -0.05
                            
                        # a2 influences a1
                        nudge_2_on_1 = 0.0
                        if act2 == 2:
                            s1["budget_anxiety"] += 0.05 * (1.0 - s1["financial_literacy"])
                            nudge_2_on_1 = 0.05
                        elif act2 == 0 and z in ["Mall", "Café", "Theater"]:
                            s1["discretionary_appetite"] += 0.05 * (1.0 - s1["financial_literacy"])
                            nudge_2_on_1 = 0.05
                        elif act2 == 1:
                            s1["budget_anxiety"] -= 0.05 * (1.0 - s1["financial_literacy"])
                            nudge_2_on_1 = -0.05
                            
                        # Clamp values
                        s1["budget_anxiety"] = max(0.0, min(1.0, s1["budget_anxiety"]))
                        s1["discretionary_appetite"] = max(0.0, min(1.0, s1["discretionary_appetite"]))
                        s2["budget_anxiety"] = max(0.0, min(1.0, s2["budget_anxiety"]))
                        s2["discretionary_appetite"] = max(0.0, min(1.0, s2["discretionary_appetite"]))
                        
                        co_located_pairs.append({
                            "agent_a": a1,
                            "agent_b": a2,
                            "zone": z,
                            "nudge_a_on_b": nudge_1_on_2,
                            "nudge_b_on_a": nudge_2_on_1
                        })

            # ── 3. Compute risk score (Module 8) for the current macro state ─
            macro_now = env._macro_snapshot()
            active_aids = list(actions.keys())
            avg_budget_anxiety = sum(agent_states[aid]["budget_anxiety"] for aid in active_aids) / len(active_aids) if active_aids else 0.5
            try:
                risk_score = predict_risk_score(
                    macro_state=macro_now,
                    agent_state={
                        "budget_anxiety":     avg_budget_anxiety,
                        "essential_pressure": base_essential_pressure,
                        "liquidity":          0.5,
                    },
                )
            except Exception as exc:
                logger.warning("risk score prediction failed at tick %d: %s", tick, exc)
                risk_score = None

            # ── 4. Build per-agent action summary for the tick payload ────────
            agent_actions = {}
            for aid, action in actions.items():
                a_type, a_mag = action
                agent_actions[aid] = {
                    "action_type": int(a_type),
                    "magnitude":   float(a_mag[0]),
                    "reward":      rewards.get(aid, 0.0),
                }

            needs_state_payload = {}
            zone_payload = {}
            for aid in actions.keys():
                st = agent_states[aid]
                needs_state_payload[aid] = {
                    "budget_anxiety": st["budget_anxiety"],
                    "essential_pressure": st["essential_pressure"],
                    "discretionary_appetite": st["discretionary_appetite"]
                }
                zone_payload[aid] = st["zone"]

            # ── 5. Persist episodes to Qdrant (Module 7) ─────────────────────
            event_payload = {"tick": tick, "macro": macro_now}
            for aid, action in actions.items():
                a_type, a_mag = action
                outcome_payload = {k: v for k, v in infos.get(aid, {}).items()
                                   if k != "macro"}
                try:
                    store_episode(
                        agent_id=aid,
                        event=event_payload,
                        action={"action_type": int(a_type), "magnitude": float(a_mag[0])},
                        outcome=outcome_payload,
                    )
                except Exception as exc:
                    logger.warning(
                        "Memory store_episode failed for agent %s at tick %d: %s",
                        aid, tick, exc,
                    )

            # ── 6. Send tick message to the WebSocket client ──────────────────
            tick_message = {
                "tick":             tick,
                "agent_actions":    agent_actions,
                "needs_state":      needs_state_payload,
                "zone":             zone_payload,
                "co_located_pairs": co_located_pairs,
                "macro_state":      macro_now,
                "risk_score":       risk_score,
                "active_agents":    len(actions.keys()),
                "policy":           runner.mode,
                "shock":            shock.to_dict(),
            }
            await websocket.send_json(tick_message)
            await asyncio.sleep(_TICK_DELAY_SECONDS)

        await websocket.send_json({"status": "simulation_complete"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for run %s", run_id)
    except Exception as exc:
        logger.exception("WebSocket error for run %s: %s", run_id, exc)
        try:
            await websocket.send_json({"error": str(exc)})
        except Exception:
            pass
