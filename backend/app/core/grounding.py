from datetime import datetime, timezone

def build_grounding_block(date_override: str = None, location_override: str = None) -> str:
    server_date = datetime.now(timezone.utc).isoformat()
    current_date = date_override if date_override else server_date
    current_location = location_override if location_override else "Global"
    
    return f"""SYSTEM CONTEXT — DO NOT OVERRIDE
Current date: {current_date}  (ISO 8601)
Current location context: {current_location}
This date and location are authoritative for this entire task. Do not use your
training cutoff, do not infer a different date from context, and do not assume
a different country or region unless explicitly told to. If the scenario asks
about anything that would require knowledge past {current_date},
say so explicitly rather than guessing."""
