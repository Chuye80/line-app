from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import get_settings


_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=1800,
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
    except Exception:
        # Without this an endpoint that raises leaves a half-applied
        # transaction on a pooled connection for the next request to inherit.
        db.rollback()
        raise
    finally:
        db.close()
