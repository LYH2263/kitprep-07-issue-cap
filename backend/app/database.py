from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns() -> None:
    """Add columns introduced after initial deploy to pre-existing tables.

    create_all only creates missing tables; these ALTERs are idempotent so
    upgrades of an existing volume pick up daily_limit / biz_date.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        if "ingredients" in tables:
            cols = {c["name"] for c in insp.get_columns("ingredients")}
            if "daily_limit" not in cols:
                conn.execute(text(
                    "ALTER TABLE ingredients ADD COLUMN daily_limit FLOAT DEFAULT 0.0 NOT NULL"
                ))
        if "prep_runs" in tables:
            cols = {c["name"] for c in insp.get_columns("prep_runs")}
            if "biz_date" not in cols:
                conn.execute(text("ALTER TABLE prep_runs ADD COLUMN biz_date DATE"))
