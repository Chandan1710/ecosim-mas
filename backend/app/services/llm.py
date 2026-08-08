import os
import json
import logging
from groq import Groq
from app.core.grounding import build_grounding_block
from app.api.endpoints.models import ScenarioParseResponse

logger = logging.getLogger(__name__)

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

def parse_scenario_with_llm(description: str, date_override: str = None, location_override: str = None) -> ScenarioParseResponse:
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    if not groq_api_key:
        logger.warning("GROQ_API_KEY is missing, falling back to mock response.")
        return ScenarioParseResponse(
            understood=["Parsed mock scenario fallback"],
            region=None,
            time_horizon_months=None,
            primary_event="Mock event due to missing API key.",
            affected_sectors=[],
            ambiguous_or_missing=[{"field": "region", "question": "What region does this apply to?"}]
        )

    client = Groq(api_key=groq_api_key)
    grounding = build_grounding_block(date_override, location_override)
    
    system_prompt = f"{grounding}\n\n{SCENARIO_PARSER_PROMPT}"
    
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
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description}
        ],
        response_format=SCENARIO_SCHEMA,
        temperature=0.0
    )
    
    content = response.choices[0].message.content
    try:
        data = json.loads(content)
        return ScenarioParseResponse(**data)
    except Exception as e:
        logger.error(f"Failed to parse LLM output as JSON: {e}")
        # Return fallback on parsing error
        return ScenarioParseResponse(
            understood=[],
            primary_event="Error parsing response",
            affected_sectors=[],
            ambiguous_or_missing=[{"field": "all", "question": "Could not parse scenario clearly. Please clarify."}]
        )
