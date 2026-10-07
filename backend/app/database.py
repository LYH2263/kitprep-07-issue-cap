from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema(bind=engine) -> None:
    """create_all 建新表，再给旧库幂等补列（SQLite/Postgres 通用）。"""
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    with bind.begin() as conn:
        if "ingredients" in tables and \
                "daily_limit" not in {c["name"] for c in inspector.get_columns("ingredients")}:
            conn.execute(text("ALTER TABLE ingredients ADD COLUMN daily_limit FLOAT DEFAULT 0.0"))
        if "prep_runs" in tables and \
                "business_date" not in {c["name"] for c in inspector.get_columns("prep_runs")}:
            # 旧备料单补当日维度；历史行回填当天，占用按新口径另起。
            conn.execute(text("ALTER TABLE prep_runs ADD COLUMN business_date DATE"))
            conn.execute(text("UPDATE prep_runs SET business_date = CURRENT_DATE "
                              "WHERE business_date IS NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prep_runs_business_date "
                              "ON prep_runs (business_date)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
