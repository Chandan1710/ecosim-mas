from sqlalchemy import Column, Integer, String, Float
from db.base_class import Base

class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    
    # Archetype fields defined in the prompt
    risk_appetite = Column(Float, nullable=False)
    financial_literacy = Column(Float, nullable=False)
    spending_bias = Column(Float, nullable=False)
