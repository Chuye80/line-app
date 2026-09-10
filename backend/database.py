import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to the project .env file."
    )


_ENGINE_KWARGS = {
    "pool_pre_ping": True,
    "pool_recycle": 600,
    "connect_args": {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
}

engine = create_engine(
    DATABASE_URL,
    pool_size=8,
    max_overflow=4,
    **_ENGINE_KWARGS,
)

read_engine = create_engine(
    DATABASE_URL,
    isolation_level="AUTOCOMMIT",
    pool_size=4,
    max_overflow=2,
    **_ENGINE_KWARGS,
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
