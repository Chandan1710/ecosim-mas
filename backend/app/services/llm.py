from __future__ import annotations
import os
import json
import logging
from typing import List, Optional
import httpx
from groq import Groq, APITimeoutError, RateLimitError
from app.core.grounding import build_grounding_block
from app.api.endpoints.models import ScenarioParseResponse, CausalChainResponse, CausalNode

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = "qwen2.5:7b"
GROQ_TIMEOUT_SECONDS = 15

# ─────────────────────────── shared Groq client helper ──────────────────────

def _groq_client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — Scenario Parser
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_PARSER_PROMPT = """You are the Scenario Parser for EcoSim-MAS, an economic shock simulation system.
Your only job is to read the user's scenario description and extract a structured
understanding of it. You do NOT generate a causal chain and you do NOT run any
simulation.

Return JSON with exactly these fields:
{
  "understood": [ "short bullet describing a concrete thing you understood" ],
  "region": "string or null if not specified",
  "time_horizon_months": "integer or null if not specified",
  "primary_event": "one-sentence description of the triggering event",
  "affected_sectors": [ "sector names you can confidently infer" ],
  "ambiguous_or_missing": [
    { "field": "what is unclear", "question": "a direct question to ask the user" }
  ]
}

Rules:
- Never invent a region, time horizon, or magnitude the user did not state or
  strongly imply. If it is not there, put it in ambiguous_or_missing instead of
  guessing a default.
- "ambiguous_or_missing" should be empty only if the scenario is genuinely
  unambiguous — do not leave it empty just to seem helpful.
- Keep each question in ambiguous_or_missing short and answerable in one line.
- Do not include any text outside the JSON object."""

SCENARIO_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "scenario_parser_response",
        "schema": {
            "type": "object",
            "properties": {
                "understood": {"type": "array", "items": {"type": "string"}},
                "region": {"type": ["string", "null"]},
                "time_horizon_months": {"type": ["integer", "null"]},
                "primary_event": {"type": "string"},
                "affected_sectors": {"type": "array", "items": {"type": "string"}},
                "ambiguous_or_missing": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "question": {"type": "string"},
                        },
                        "required": ["field", "question"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "understood", "region", "time_horizon_months",
                "primary_event", "affected_sectors", "ambiguous_or_missing",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _mock_fallback_response() -> ScenarioParseResponse:
    """Final hardcoded fallback — only fires if both Groq and Ollama are unreachable."""
    return ScenarioParseResponse(
        understood=["Parsed mock scenario fallback"],
        region=None,
        time_horizon_months=None,
        primary_event="Mock event due to missing API key and unreachable Ollama.",
        affected_sectors=[],
        ambiguous_or_missing=[{"field": "region", "question": "What region does this apply to?"}],
    )


def _parse_json_to_response(content: str) -> ScenarioParseResponse:
    data = json.loads(content)
    return ScenarioParseResponse(**data)


def _call_ollama(system_prompt: str, description: str) -> ScenarioParseResponse:
    logger.warning(
        "FALLBACK: Groq failed — calling Ollama (%s at %s). "
        "This is a reliability event worth tracking.",
        OLLAMA_MODEL, OLLAMA_BASE_URL,
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ],
        "stream": False,
        "format": "json",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()

    content = resp.json()["message"]["content"]
    return _parse_json_to_response(content)


def _call_groq_with_fallback(
    system_prompt: str,
    user_content: str,
    response_format: dict,
    parse_fn,
    ollama_fallback_fn,
    groq_api_key: Optional[str],
):
    """
    Shared three-tier fallback driver used by both the Scenario Parser and the
    Causal Chain Engine.

    Tier 0: no API key → skip Groq, try Ollama.
    Tier 1: Groq timeout / rate-limit / bad JSON after one retry → try Ollama.
    Tier 2: Ollama also fails → return None (caller supplies its own final fallback).
    """
    if not groq_api_key:
        logger.warning("GROQ_API_KEY is missing — skipping Groq, trying Ollama next.")
        try:
            return ollama_fallback_fn(system_prompt, user_content)
        except Exception as e:
            logger.error("Ollama also unreachable (%s).", e)
            return None

    client = _groq_client()
    should_try_ollama = False

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format=response_format,
                temperature=0.0,
                timeout=GROQ_TIMEOUT_SECONDS,
            )
            content = resp.choices[0].message.content
            return parse_fn(content)

        except APITimeoutError as e:
            logger.warning("Groq timeout on attempt %d: %s", attempt + 1, e)
            should_try_ollama = True
            break

        except RateLimitError as e:
            logger.warning("Groq rate-limited on attempt %d: %s", attempt + 1, e)
            should_try_ollama = True
            break

        except Exception as e:
            logger.warning("Groq error on attempt %d: %s", attempt + 1, e)
            if attempt == 1:
                should_try_ollama = True

    if should_try_ollama:
        try:
            return ollama_fallback_fn(system_prompt, user_content)
        except Exception as e:
            logger.error("Ollama fallback also failed (%s).", e)

    return None


def parse_scenario_with_llm(
    description: str,
    date_override: str = None,
    location_override: str = None,
) -> ScenarioParseResponse:
    groq_api_key = os.getenv("GROQ_API_KEY")
    grounding = build_grounding_block(date_override, location_override)
    system_prompt = f"{grounding}\n\n{SCENARIO_PARSER_PROMPT}"

    result = _call_groq_with_fallback(
        system_prompt=system_prompt,
        user_content=description,
        response_format=SCENARIO_SCHEMA,
        parse_fn=_parse_json_to_response,
        ollama_fallback_fn=_call_ollama,
        groq_api_key=groq_api_key,
    )
    return result if result is not None else _mock_fallback_response()


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — Causal Chain Engine
# ═══════════════════════════════════════════════════════════════════════════

CAUSAL_CHAIN_PROMPT = """You are the Causal Chain Engine for EcoSim-MAS. Given a primary economic event
and current macro context, produce a ranked causal chain of 10 to 15 downstream
consequences, ordered from the most economically significant to the most minor.

Ground every step in real economic mechanisms (supply/demand, cost pass-through,
policy response, behavioural response) — do not invent effects with no plausible
transmission mechanism.

Return JSON matching this schema:
{
  "chain": [
    {
      "node_id": "integer, 1-indexed, in causal order",
      "description": "one clear sentence describing this consequence",
      "magnitude": "major | moderate | minor",
      "category": "prices | employment | credit | policy | consumer_behaviour | trade | other",
      "depends_on": [ "node_id(s) this follows from, or [] if it follows directly from the primary event" ],
      "confidence": "float 0-1, your confidence this consequence actually follows"
    }
  ]
}

Constraints:
- Exactly 10 to 15 nodes.
- node_id 1 must follow directly from the primary event (depends_on must be []).
- Order nodes from majorly-impacting to minor — do not cluster all "major" nodes
  arbitrarily; order should reflect the actual causal cascade.
- If you are not confident about a downstream effect, include it with a lower
  confidence score rather than omitting it — the simulation layer will weight
  by confidence.
- Do not include any text outside the JSON object."""

CAUSAL_CHAIN_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "causal_chain_response",
        "schema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "array",
                    "minItems": 10,
                    "maxItems": 15,
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_id": {"type": "integer"},
                            "description": {"type": "string"},
                            "magnitude": {
                                "type": "string",
                                "enum": ["major", "moderate", "minor"],
                            },
                            "category": {
                                "type": "string",
                                "enum": [
                                    "prices", "employment", "credit",
                                    "policy", "consumer_behaviour", "trade", "other",
                                ],
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "node_id", "description", "magnitude",
                            "category", "depends_on", "confidence",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["chain"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _mock_causal_chain() -> list[dict]:
    """Hardcoded 10-node mock used when both Groq and Ollama are unavailable."""
    return [
        {"node_id": i, "description": f"Mock consequence {i}", "magnitude": "minor",
         "category": "other", "depends_on": [] if i == 1 else [i - 1], "confidence": 0.5}
        for i in range(1, 11)
    ]


def _parse_chain_content(content: str) -> list[dict]:
    """Parse raw JSON string into the chain list; raises on failure."""
    data = json.loads(content)
    return data["chain"]


def _call_ollama_chain(system_prompt: str, user_content: str) -> list[dict]:
    """Call Ollama for the causal chain; returns the parsed chain list."""
    logger.warning(
        "FALLBACK: Groq failed on causal chain — calling Ollama (%s at %s). "
        "This is a reliability event worth tracking.",
        OLLAMA_MODEL, OLLAMA_BASE_URL,
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": "json",
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return _parse_chain_content(content)


def generate_causal_chain(
    primary_event: str,
    region: Optional[str] = None,
    time_horizon_months: Optional[int] = None,
    affected_sectors: Optional[List[str]] = None,
    date_override: Optional[str] = None,
    location_override: Optional[str] = None,
) -> List[dict]:
    """
    Call Groq → Ollama → mock to produce a 10-15 node causal chain.
    Returns the raw chain list (dicts); the endpoint layer handles DB persistence.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    grounding = build_grounding_block(date_override, location_override)

    context_lines = [f"Primary event: {primary_event}"]
    if region:
        context_lines.append(f"Region: {region}")
    if time_horizon_months:
        context_lines.append(f"Time horizon: {time_horizon_months} months")
    if affected_sectors:
        context_lines.append(f"Affected sectors: {', '.join(affected_sectors)}")
    user_content = "\n".join(context_lines)

    system_prompt = f"{grounding}\n\n{CAUSAL_CHAIN_PROMPT}"

    result = _call_groq_with_fallback(
        system_prompt=system_prompt,
        user_content=user_content,
        response_format=CAUSAL_CHAIN_SCHEMA,
        parse_fn=_parse_chain_content,
        ollama_fallback_fn=_call_ollama_chain,
        groq_api_key=groq_api_key,
    )
    return result if result is not None else _mock_causal_chain()


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 6 — Semantic-to-Numerical Mapper
# ═══════════════════════════════════════════════════════════════════════════
# Runs ONCE PER NODE (not per agent per tick) to convert a qualitative
# causal-chain node into numeric deltas that seed EcoSimEnv's macro state.
# Output schema matches §8.4 exactly.

SEMANTIC_MAPPER_PROMPT = """You are the Semantic-to-Numerical Mapper for EcoSim-MAS. You convert one causal
chain node into numeric deltas that seed the multi-agent simulation's macro
state. You do not decide what any individual agent does — you only translate
a qualitative event into a starting quantitative signal.

Given a causal chain node and the current macro state, return JSON:
{
  "node_id": "matches the input node_id",
  "deltas": {
    "discretionary_spend_pct": "float, e.g. -0.15 for a 15% decrease",
    "savings_rate_pct": "float",
    "essential_cost_index_pct": "float",
    "credit_availability_pct": "float"
  },
  "rationale": "one sentence explaining the mapping"
}

Rules:
- Deltas must be directionally consistent with the node's description and
  magnitude (major nodes should generally produce larger-magnitude deltas than
  minor nodes, but use judgement — a "major" policy announcement can have a
  smaller immediate numeric effect than a "moderate" supply shock).
- All delta values must be floats in the range -1.0 to 1.0.
- These deltas seed the environment state only. They are not final outcomes —
  the agent policies will react to them during simulation.
- Do not include any text outside the JSON object."""

SEMANTIC_MAPPER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "semantic_mapper_response",
        "schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer"},
                "deltas": {
                    "type": "object",
                    "properties": {
                        "discretionary_spend_pct": {"type": "number"},
                        "savings_rate_pct": {"type": "number"},
                        "essential_cost_index_pct": {"type": "number"},
                        "credit_availability_pct": {"type": "number"},
                    },
                    "required": [
                        "discretionary_spend_pct",
                        "savings_rate_pct",
                        "essential_cost_index_pct",
                        "credit_availability_pct",
                    ],
                    "additionalProperties": False,
                },
                "rationale": {"type": "string"},
            },
            "required": ["node_id", "deltas", "rationale"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}

# Default magnitude → scalar scale so the mock is directionally meaningful
_MAGNITUDE_SCALE = {"major": 0.15, "moderate": 0.08, "minor": 0.03}


def _mock_node_delta(node: dict) -> dict:
    """Rule-based mock used when both Groq and Ollama are unavailable.

    Produces directionally plausible deltas based on node category and
    magnitude so downstream tests remain meaningful even without an LLM.
    """
    scale = _MAGNITUDE_SCALE.get(node.get("magnitude", "minor"), 0.03)
    category = node.get("category", "other")

    # Direction heuristics per category — conservative, not a model
    if category == "credit":
        deltas = {
            "discretionary_spend_pct": -scale,
            "savings_rate_pct": scale * 0.5,
            "essential_cost_index_pct": 0.0,
            "credit_availability_pct": -scale,
        }
    elif category == "prices":
        deltas = {
            "discretionary_spend_pct": -scale,
            "savings_rate_pct": -scale * 0.3,
            "essential_cost_index_pct": scale,
            "credit_availability_pct": 0.0,
        }
    elif category == "employment":
        deltas = {
            "discretionary_spend_pct": -scale,
            "savings_rate_pct": scale * 0.2,
            "essential_cost_index_pct": 0.0,
            "credit_availability_pct": -scale * 0.5,
        }
    elif category == "consumer_behaviour":
        deltas = {
            "discretionary_spend_pct": scale * 0.4,
            "savings_rate_pct": -scale * 0.2,
            "essential_cost_index_pct": 0.0,
            "credit_availability_pct": 0.0,
        }
    elif category == "policy":
        deltas = {
            "discretionary_spend_pct": -scale * 0.5,
            "savings_rate_pct": scale * 0.3,
            "essential_cost_index_pct": 0.0,
            "credit_availability_pct": -scale * 0.6,
        }
    else:  # trade / other
        deltas = {
            "discretionary_spend_pct": -scale * 0.3,
            "savings_rate_pct": 0.0,
            "essential_cost_index_pct": scale * 0.3,
            "credit_availability_pct": 0.0,
        }

    return {
        "node_id": node["node_id"],
        "deltas": deltas,
        "rationale": f"Mock mapping for {category} node at {node.get('magnitude', 'minor')} magnitude.",
    }


def _parse_mapper_content(content: str) -> dict:
    """Parse raw JSON from the mapper LLM call."""
    return json.loads(content)


def _call_ollama_mapper(system_prompt: str, user_content: str) -> dict:
    """Call Ollama for the semantic mapper; returns the parsed delta dict."""
    logger.warning(
        "FALLBACK: Groq failed on semantic mapper — calling Ollama (%s at %s). "
        "This is a reliability event worth tracking.",
        OLLAMA_MODEL, OLLAMA_BASE_URL,
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": "json",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return _parse_mapper_content(content)


def map_node_to_deltas(
    node: dict,
    macro_state: Optional[dict] = None,
    date_override: Optional[str] = None,
    location_override: Optional[str] = None,
) -> dict:
    """
    Convert ONE causal chain node into numeric deltas per §8.4.

    Parameters
    ----------
    node : dict
        A single causal chain node dict with at minimum:
          node_id, description, magnitude, category, depends_on, confidence
    macro_state : dict, optional
        Current macro state e.g.
          {"inflation_rate": 5.5, "repo_rate": 6.5, "fuel_price_index": 110.0}
        Included in the prompt so the LLM can calibrate delta magnitudes.
    date_override : str, optional
    location_override : str, optional

    Returns
    -------
    dict with keys: node_id, deltas (dict of four floats), rationale (str)
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    grounding = build_grounding_block(date_override, location_override)

    macro_snippet = ""
    if macro_state:
        macro_snippet = (
            "\nCurrent macro state:\n"
            + "\n".join(f"  {k}: {v}" for k, v in macro_state.items())
        )

    user_content = (
        f"Causal chain node:\n"
        f"  node_id: {node['node_id']}\n"
        f"  description: {node['description']}\n"
        f"  magnitude: {node['magnitude']}\n"
        f"  category: {node['category']}\n"
        f"  confidence: {node['confidence']}"
        + macro_snippet
    )

    system_prompt = f"{grounding}\n\n{SEMANTIC_MAPPER_PROMPT}"

    result = _call_groq_with_fallback(
        system_prompt=system_prompt,
        user_content=user_content,
        response_format=SEMANTIC_MAPPER_SCHEMA,
        parse_fn=_parse_mapper_content,
        ollama_fallback_fn=_call_ollama_mapper,
        groq_api_key=groq_api_key,
    )
    return result if result is not None else _mock_node_delta(node)
