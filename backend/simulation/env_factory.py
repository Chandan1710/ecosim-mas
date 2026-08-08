"""
Helpers to build the EcoSimEnv from live DB data or a fixture list.
Keeps DB concerns out of the environment itself.
"""

from __future__ import annotations

from typing import List, Optional, Dict

from simulation.ecosim_env import AgentPersona, EcoSimEnv, make_ecosim_env


def _persona_slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def personas_from_db() -> List[AgentPersona]:
    """Load all 10 personas from PostgreSQL and return AgentPersona instances."""
    from db.session import SessionLocal
    from models.personas import Persona as PersonaModel

    db = SessionLocal()
    try:
        rows = db.query(PersonaModel).order_by(PersonaModel.id).all()
    finally:
        db.close()

    return [
        AgentPersona(
            agent_id=_persona_slug(row.name),
            name=row.name,
            risk_appetite=row.risk_appetite,
            financial_literacy=row.financial_literacy,
            spending_bias=row.spending_bias,
        )
        for row in rows
    ]


def personas_from_fixtures(fixture_data: List[Dict]) -> List[AgentPersona]:
    """
    Build AgentPersona list directly from the fixture JSON dicts.
    Useful in tests so DB is not required.
    """
    return [
        AgentPersona(
            agent_id=_persona_slug(row["name"]),
            name=row["name"],
            risk_appetite=row["risk_appetite"],
            financial_literacy=row["financial_literacy"],
            spending_bias=row["spending_bias"],
        )
        for row in fixture_data
    ]


def build_env_from_db(
    initial_macro: Optional[Dict[str, float]] = None,
    max_steps: int = 100,
    seed: Optional[int] = None,
) -> EcoSimEnv:
    """Convenience constructor: load personas from DB and return a ready env."""
    personas = personas_from_db()
    return make_ecosim_env(personas=personas, initial_macro=initial_macro,
                           max_steps=max_steps, seed=seed)
