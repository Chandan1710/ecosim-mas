import pytest
from backend.db.session import SessionLocal, SessionLocalTS
from backend.models.personas import Persona
from backend.models.events import Event
from backend.models.macro_variables import MacroVariable

def test_seed_data_loaded():
    db = SessionLocal()
    db_ts = SessionLocalTS()

    try:
        # Check personas (we have 10)
        personas_count = db.query(Persona).count()
        assert personas_count == 10, f"Expected 10 personas, got {personas_count}"

        # Check events (we have 5 economic + 5 news = 10)
        events_count = db.query(Event).count()
        assert events_count == 10, f"Expected 10 events, got {events_count}"

        # Check macro variables (we have 6 records)
        macro_count = db_ts.query(MacroVariable).count()
        assert macro_count == 6, f"Expected 6 macro variables, got {macro_count}"
    finally:
        db.close()
        db_ts.close()
