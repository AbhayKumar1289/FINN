from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- reference ----------
class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    nse_symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    bse_code: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(80))
    is_financial: Mapped[bool] = mapped_column(Boolean, default=False)  # banks/NBFCs: no EBITDA, different ratios
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class PortfolioCompany(Base):
    __tablename__ = "portfolio_companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), unique=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    company: Mapped[Company] = relationship()


# ---------- source data ----------
class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("company_id", "trading_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)       # as traded (unadjusted)
    adj_close: Mapped[float] = mapped_column(Float)   # split/dividend adjusted
    volume: Mapped[int] = mapped_column(Integer)


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("source", "source_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))          # "bse" | "nse" | "snapshot"
    source_id: Mapped[str] = mapped_column(String(128))      # exchange id or content hash
    title: Mapped[str] = mapped_column(Text)
    exchange_category: Mapped[Optional[str]] = mapped_column(String(120))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    original_url: Mapped[Optional[str]] = mapped_column(Text)
    document_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    # derived (filled by pipeline)
    category: Mapped[Optional[str]] = mapped_column(String(48), index=True)
    extracted: Mapped[Optional[dict]] = mapped_column(JSON)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    why_it_matters: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[Optional[str]] = mapped_column(String(8), index=True)  # high|medium|low
    priority_score: Mapped[Optional[float]] = mapped_column(Float)
    priority_reasons: Mapped[Optional[list]] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(String(24), default="new")
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(16))


class FinancialDocument(Base):
    __tablename__ = "financial_documents"
    __table_args__ = (UniqueConstraint("company_id", "source_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(32))   # annual_report | concall_transcript | results
    title: Mapped[str] = mapped_column(Text)
    period: Mapped[Optional[str]] = mapped_column(String(16))  # e.g. FY25, Q2FY26
    published_on: Mapped[Optional[date]] = mapped_column(Date)
    source_url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="discovered")
    error: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("financial_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(Text)


# ---------- extracted facts ----------
class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (UniqueConstraint("company_id", "metric", "period", "basis"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(48))      # revenue|ebitda|pbt|pat|ocf|borrowings|cash...
    period: Mapped[str] = mapped_column(String(16))      # Q2FY26 | FY25
    value_cr: Mapped[float] = mapped_column(Float)       # always normalised to ₹ crore
    basis: Mapped[str] = mapped_column(String(16))       # consolidated | standalone
    source_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("financial_documents.id"))
    source_announcement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("announcements.id"))
    source_location: Mapped[Optional[str]] = mapped_column(Text)


class ManagementGuidance(Base):
    __tablename__ = "management_guidance"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text)               # verbatim from transcript
    guidance_type: Mapped[str] = mapped_column(String(24))     # explicit_numeric|qualitative|historical|aspirational
    metric: Mapped[Optional[str]] = mapped_column(String(48))
    target_low: Mapped[Optional[float]] = mapped_column(Float)
    target_high: Mapped[Optional[float]] = mapped_column(Float)
    target_unit: Mapped[Optional[str]] = mapped_column(String(16))   # pct | cr | pp
    target_period: Mapped[Optional[str]] = mapped_column(String(16))
    stated_in_period: Mapped[Optional[str]] = mapped_column(String(16))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("financial_documents.id"))
    source_location: Mapped[Optional[str]] = mapped_column(Text)
    scope: Mapped[Optional[str]] = mapped_column(String(16))      # company | segment
    segment: Mapped[Optional[str]] = mapped_column(String(120))


# ---------- alerts ----------
class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(32), unique=True)  # price_move | volume_spike | announcement_category
    threshold: Mapped[Optional[float]] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[Optional[float]] = mapped_column(Float)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float)
    as_of: Mapped[Optional[date]] = mapped_column(Date)  # market date the data refers to
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_reference: Mapped[Optional[dict]] = mapped_column(JSON)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------- generated analysis + ops ----------
class ResearchResult(Base):
    __tablename__ = "research_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    module: Mapped[Optional[str]] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    task: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # prices | announcements | documents
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # ok | partial | failed
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
