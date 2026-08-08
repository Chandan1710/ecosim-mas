from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from db.base_class import Base
from datetime import datetime


class CausalChain(Base):
    __tablename__ = "causal_chains"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False, index=True)
    # Full chain stored as a JSONB-compatible JSON array — each element is one node dict.
    # A separate causal_chain_nodes table would over-normalise for our query patterns;
    # we always read/write the whole chain at once, so JSON column is the right trade-off.
    chain = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
