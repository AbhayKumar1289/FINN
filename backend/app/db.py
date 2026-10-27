import shutil
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")


def _bootstrap_sqlite() -> None:
    """No database yet (first boot, or a host whose disk is wiped on redeploy): start from the
    bundled demo snapshot so the app opens with real filings and research, not an empty screen."""
    if not _is_sqlite or ":memory:" in settings.database_url or settings.database_url == "sqlite://":
        return
    target = Path(settings.database_url.split("sqlite:///", 1)[-1])
    seed = Path(settings.seed_db_path)
    if not target.exists() and seed.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed, target)


_bootstrap_sqlite()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns(engine_=None) -> list[str]:
    """Tiny forward-only migration for a prototype: add nullable columns that exist on the
    models but not yet in the database. Anything bigger would get Alembic."""
    engine_ = engine_ or engine
    insp = inspect(engine_)
    added = []
    with engine_.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                      f'{col.type.compile(engine_.dialect)}'))
                    added.append(f"{table.name}.{col.name}")
    return added
