from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.research.index import ensure_fts
from app.seed import seed

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed(session)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def feed_bytes() -> bytes:
    """Real NSE RSS items from 27 Oct 2026: every portfolio filing, two look-alike company
    names (M&M Financial, NTPC Green) and some unrelated filings."""
    return (FIXTURES / "nse_announcements_sample.xml").read_bytes()
