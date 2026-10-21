import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# PostgreSQL connection
DEFAULT_PG_URL = "postgresql://ecosim:ecosim@localhost:5432/ecosim"
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_PG_URL)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# TimescaleDB connection
DEFAULT_TS_URL = "postgresql://ecosim_ts:ecosim_ts@localhost:5433/ecosim_ts"
SQLALCHEMY_TS_DATABASE_URL = os.getenv("TIMESCALE_DATABASE_URL", DEFAULT_TS_URL)

engine_ts = create_engine(SQLALCHEMY_TS_DATABASE_URL)
SessionLocalTS = sessionmaker(autocommit=False, autoflush=False, bind=engine_ts)
