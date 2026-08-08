from sqlalchemy import Column, Integer, String, DateTime, Text
from db.base_class import Base
from datetime import datetime

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True, nullable=False)  # e.g., 'GDELT', 'NewsAPI'
    raw_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
