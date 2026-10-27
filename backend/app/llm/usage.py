from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LLMCall


def llm_usage(db: Session) -> dict:
    """Spend by task and model. Cache hits never reach this table, so it is billable calls only."""
    rows = db.execute(select(LLMCall.task, LLMCall.model, func.count(LLMCall.id),
                             func.sum(LLMCall.input_tokens), func.sum(LLMCall.output_tokens),
                             func.sum(LLMCall.cost_usd))
                      .group_by(LLMCall.task, LLMCall.model)).all()
    by_task = [{"task": t, "model": m, "calls": n, "input_tokens": i or 0, "output_tokens": o or 0,
                "cost_usd": round(c or 0, 5)} for t, m, n, i, o, c in rows]
    return {"calls": sum(r["calls"] for r in by_task),
            "cost_usd": round(sum(r["cost_usd"] for r in by_task), 5),
            "by_task": by_task}
