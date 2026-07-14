from sqlalchemy.orm import declarative_base

from app.database.engine import get_engine, get_session_factory

# Shared connection pool engine
engine = get_engine()

# Shared session factory
SessionLocal = get_session_factory()

Base = declarative_base()


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
