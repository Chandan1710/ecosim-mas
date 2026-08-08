import json
import os
from datetime import datetime

from backend.db.session import SessionLocal, SessionLocalTS
from backend.models.personas import Persona
from backend.models.events import Event
from backend.models.macro_variables import MacroVariable

def load_json(filename):
    filepath = os.path.join(os.path.dirname(__file__), "..", "fixtures", filename)
    with open(filepath, "r") as f:
        return json.load(f)

def seed_db():
    print("Loading fixtures...")
    personas_data = load_json("personas.json")
    economic_events_data = load_json("economic_events.json")
    news_articles_data = load_json("news_articles.json")
    macro_readings_data = load_json("rbi_macro_readings.json")

    # Connect to PostgreSQL
    db = SessionLocal()
    try:
        print("Seeding Personas...")
        for p_data in personas_data:
            existing = db.query(Persona).filter(Persona.name == p_data["name"]).first()
            if not existing:
                persona = Persona(**p_data)
                db.add(persona)
        
        print("Seeding Events...")
        for e_data in economic_events_data + news_articles_data:
            ts = datetime.fromisoformat(e_data["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            existing = db.query(Event).filter(Event.raw_text == e_data["raw_text"]).first()
            if not existing:
                event = Event(source=e_data["source"], raw_text=e_data["raw_text"], timestamp=ts)
                db.add(event)
        
        db.commit()
    finally:
        db.close()

    # Connect to TimescaleDB
    db_ts = SessionLocalTS()
    try:
        print("Seeding Macro Variables...")
        for m_data in macro_readings_data:
            ts = datetime.fromisoformat(m_data["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            existing = db_ts.query(MacroVariable).filter(
                MacroVariable.variable_name == m_data["variable_name"],
                MacroVariable.timestamp == ts
            ).first()
            if not existing:
                var = MacroVariable(
                    variable_name=m_data["variable_name"],
                    value=m_data["value"],
                    timestamp=ts
                )
                db_ts.add(var)
        db_ts.commit()
    finally:
        db_ts.close()
    
    print("Seeding completed successfully.")

if __name__ == "__main__":
    seed_db()
