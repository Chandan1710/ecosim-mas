import os
import json
import logging
import httpx
from groq import Groq, APITimeoutError, RateLimitError
from app.core.grounding import build_grounding_block
from app.api.endpoints.models import ScenarioParseResponse

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = "qwen2.5:7b"
GROQ_TIMEOUT_SECONDS = 15

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
                "understood": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "region": {
                    "type": ["string", "null"]
                },
                "time_horizon_months": {
                    "type": ["integer", "null"]
                },
                "primary_event": {
                    "type": "string"
                },
                "affected_sectors": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "ambiguous_or_missing": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "question": {"type": "string"}
                        },
                        "required": ["field", "question"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["understood", "region", "time_horizon_months", "primary_event", "affected_sectors", "ambiguous_or_missing"],
            "additionalProperties": False
        },
        "strict": True
    }
}

def _mock_fallback_response() -> ScenarioParseResponse:
    """Final hardcoded fallback — only fires if both Groq and Ollama are unreachable."""
    return ScenarioParseResponse(
        understood=["Parsed mock scenario fallback"],
        region=None,
        time_horizon_months=None,
        primary_event="Mock event due to missing API key and unreachable Ollama.",
        affected_sectors=[],
        ambiguous_or_missing=[{"field": "region", "question": "What region does this apply to?"}]
    )

def _parse_json_to_response(content: str) -> ScenarioParseResponse:
    """Parse a JSON string into ScenarioParseResponse. Raises on failure."""
    data = json.loads(content)
    return ScenarioParseResponse(**data)

def _call_ollama(system_prompt: str, description: str) -> ScenarioParseResponse:
    """
    Call local Ollama with qwen2.5:7b and parse the result against the schema.
    Raises httpx.RequestError or ValueError if unreachable or unparseable.
    """
    logger.warning(
        "FALLBACK: Groq failed — calling Ollama (%s at %s). "
        "This is a reliability event worth tracking.",
        OLLAMA_MODEL, OLLAMA_BASE_URL
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description}
        ],
        "stream": False,
        "format": "json",
    }
    # Generous timeout since local models can be slow on CPU
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()

    content = resp.json()["message"]["content"]
    # One parse attempt — schema mismatch raises ValueError, which the caller catches
    return _parse_json_to_response(content)


def parse_scenario_with_llm(
    description: str,
    date_override: str = None,
    location_override: str = None,
) -> ScenarioParseResponse:
    groq_api_key = os.getenv("GROQ_API_KEY")
    grounding = build_grounding_block(date_override, location_override)
    system_prompt = f"{grounding}\n\n{SCENARIO_PARSER_PROMPT}"

    # ── Tier 0: no API key at all → skip straight to Ollama ────────────────
    if not groq_api_key:
        logger.warning("GROQ_API_KEY is missing — skipping Groq, trying Ollama next.")
        try:
            return _call_ollama(system_prompt, description)
        except Exception as ollama_err:
            logger.error("Ollama also unreachable (%s) — using hardcoded mock.", ollama_err)
            return _mock_fallback_response()

    # ── Tier 1: try Groq ────────────────────────────────────────────────────
    client = Groq(api_key=groq_api_key)
    groq_content: str | None = None
    should_try_ollama = False

    for attempt in range(2):   # one initial try + one retry on bad JSON
        try:
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": description},
                ],
                response_format=SCENARIO_SCHEMA,
                temperature=0.0,
                timeout=GROQ_TIMEOUT_SECONDS,
            )
            groq_content = response.choices[0].message.content
            return _parse_json_to_response(groq_content)

        except APITimeoutError as e:
            logger.warning("Groq timeout on attempt %d: %s", attempt + 1, e)
            should_try_ollama = True
            break  # no point retrying a timeout

        except RateLimitError as e:
            logger.warning("Groq rate-limited on attempt %d: %s", attempt + 1, e)
            should_try_ollama = True
            break  # rate-limit won't clear between retries

        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Groq bad JSON on attempt %d: %s", attempt + 1, e)
            if attempt == 1:
                # Second attempt also failed → escalate to Ollama
                should_try_ollama = True

    # ── Tier 2: Ollama ──────────────────────────────────────────────────────
    if should_try_ollama:
        try:
            return _call_ollama(system_prompt, description)
        except Exception as ollama_err:
            logger.error("Ollama fallback also failed (%s) — using hardcoded mock.", ollama_err)

    # ── Tier 3: hardcoded mock ──────────────────────────────────────────────
    return _mock_fallback_response()
