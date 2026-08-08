from sqlalchemy import Column, String, Float, DateTime
from db.base_class_ts import BaseTS

class MacroVariable(BaseTS):
    __tablename__ = "macro_variables"

    timestamp = Column(DateTime, primary_key=True, index=True)
    variable_name = Column(String, primary_key=True, index=True) # 'inflation_rate', 'repo_rate', 'fuel_price_index'
    value = Column(Float, nullable=False)
