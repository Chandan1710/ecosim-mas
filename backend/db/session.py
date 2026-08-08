from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# PostgreSQL connection
SQLALCHEMY_DATABASE_URL = "postgresql://ecosim:ecosim@localhost:5432/ecosim"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# TimescaleDB connection
SQLALCHEMY_TS_DATABASE_URL = "postgresql://ecosim_ts:ecosim_ts@localhost:5433/ecosim_ts"
engine_ts = create_engine(SQLALCHEMY_TS_DATABASE_URL)
SessionLocalTS = sessionmaker(autocommit=False, autoflush=False, bind=engine_ts)
