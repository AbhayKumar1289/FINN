"""Gemini client with model routing, a response cache and cost logging.

Routing: "cheap" (flash-lite) for bulk extraction, "strong" (flash) for escalation and
reasoning. Every call is keyed by a hash of model + prompt + attachments + schema; a repeat
is served from the llm_calls table at zero cost, so re-running the pipeline is free."""
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LLMCall

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# USD per 1M tokens (input, output), list prices used for the cost log. On the free tier the
# real spend is zero; the log still shows what the same workload would cost when paid.
PRICES = {"flash-lite": (0.10, 0.40), "flash": (0.30, 2.50), "pro": (1.25, 10.00)}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: object            # parsed JSON when a schema was given, else text
    model: str
    cached: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    sources: list = field(default_factory=list)  # [{title, uri}] from search grounding


def model_for(tier: str) -> str:
    return {"cheap": settings.model_cheap, "strong": settings.model_strong}[tier]


def _price(model: str) -> tuple[float, float]:
    for key in ("flash-lite", "flash", "pro"):  # most specific first
        if key in model:
            return PRICES[key]
    return PRICES["flash"]


def pdf_part(data: bytes) -> dict:
    return {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(data).decode()}}


def _cache_key(model: str, system: str | None, parts: list, schema: dict | None, search: bool) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"m": model, "s": system, "schema": schema, "search": search}, sort_keys=True).encode())
    for p in parts:
        if "inline_data" in p:  # hash the attachment, not its base64 text
            h.update(hashlib.sha256(p["inline_data"]["data"].encode()).digest())
        else:
            h.update(json.dumps(p, sort_keys=True).encode())
    return h.hexdigest()


def _post(model: str, body: dict) -> dict:
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set")
    delay = 4.0
    for attempt in range(4):
        r = httpx.post(API.format(model=model), json=body, timeout=180,
                       headers={"x-goog-api-key": settings.gemini_api_key})
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 503) and attempt < 3:
            log.warning("gemini %s %s; retrying in %.0fs", model, r.status_code, delay)
            time.sleep(delay)
            delay *= 2
            continue
        raise LLMError(f"gemini {model} {r.status_code}: {r.text[:300]}")
    raise LLMError("unreachable")


def generate(db: Session, task: str, parts: list, *, tier: str = "cheap", system: str | None = None,
             schema: dict | None = None, search: bool = False,
             thinking: str | None = None) -> LLMResult:
    """thinking="low" caps reasoning tokens for transcription-style tasks, where thinking is
    pure cost (it was ~85% of the strong model's output tokens on results extraction)."""
    model = model_for(tier)
    key = _cache_key(model, f"{system}|thinking={thinking}", parts, schema, search)
    hit = db.scalar(select(LLMCall).where(LLMCall.cache_key == key))
    if hit is not None:
        return LLMResult(hit.response.get("data"), model, True, sources=hit.response.get("sources", []))

    body: dict = {"contents": [{"role": "user", "parts": parts}],
                  "generationConfig": {"temperature": 0}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if schema:
        body["generationConfig"] |= {"responseMimeType": "application/json", "responseSchema": schema}
    if search:
        body["tools"] = [{"google_search": {}}]
    if thinking:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}

    try:
        resp = _post(model, body)
    except LLMError as exc:
        if not (thinking and "thinking" in str(exc).lower()):
            raise
        body["generationConfig"].pop("thinkingConfig")  # model doesn't support the knob
        resp = _post(model, body)
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                   if not p.get("thought"))
    if not text:
        raise LLMError(f"empty response (finishReason={cand.get('finishReason')})")
    data = json.loads(text) if schema else text.strip()

    usage = resp.get("usageMetadata") or {}
    tin = usage.get("promptTokenCount", 0)
    tout = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    pin, pout = _price(model)
    cost = (tin * pin + tout * pout) / 1e6
    sources = [{"title": (c.get("web") or {}).get("title"), "uri": (c.get("web") or {}).get("uri")}
               for c in (cand.get("groundingMetadata") or {}).get("groundingChunks", [])]

    db.add(LLMCall(cache_key=key, task=task, model=model, input_tokens=tin, output_tokens=tout,
                   cost_usd=cost, response={"data": data, "sources": sources}))
    db.commit()
    log.info("llm %s %s in=%d out=%d $%.5f", task, model, tin, tout, cost)
    return LLMResult(data, model, False, tin, tout, cost, sources)
